import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
import socket
import cv2
import numpy as np
from prometheus_fastapi_instrumentator import Instrumentator
from logging_config import get_logger
from fastapi import Depends
from utils.fastapi_image_upload import (
    MAX_UPLOAD_BYTES,
    STREAM_KEY,
    close_redis_client,
    first_value,
    get_redis_client,
    metadata_value,
    normalize_captured_at,
    normalize_image_format,
    now_str,
    parse_metadata,
    publish_completed_event,
    require_redis_client,
    safe_id,
    save_upload_file,
)


HEATMAP_STREAM_KEY = os.getenv("HEATMAP_STREAM_KEY", "heatmap")
# 업로드된 RGB 이미지를 저장할 컨테이너 내부 경로
IMAGE_SAVE_DIR = os.getenv("IMG_SAVE_DIR", "/app/images")
# 업로드된 IR 이미지를 저장할 컨테이너 내부 경로
IR_IMAGE_SAVE_DIR = os.getenv("IR_IMG_SAVE_DIR", "/app/images/irs")
# Uploaded heatmap image save directory
HEATMAP_IMAGE_SAVE_DIR = os.getenv("HEATMAP_IMG_SAVE_DIR", "/app/images/heatmaps")
# FastAPI 업로드 서버가 바인딩할 주소
HTTP_HOST = os.getenv("HTTP_HOST", "0.0.0.0")
# FastAPI 업로드 서버가 바인딩할 포트
HTTP_PORT = int(os.getenv("HTTP_PORT", "8000"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        require_redis_client()
    except Exception as exc:
        print(f"[FIRE-DETECT-UPLOAD] Redis connection failed: {exc}")

    Path(IMAGE_SAVE_DIR).mkdir(parents=True, exist_ok=True)
    Path(IR_IMAGE_SAVE_DIR).mkdir(parents=True, exist_ok=True)
    Path(HEATMAP_IMAGE_SAVE_DIR).mkdir(parents=True, exist_ok=True)
    print(f"[FIRE-DETECT-UPLOAD] HTTP upload server: {HTTP_HOST}:{HTTP_PORT}")
    print(f"[FIRE-DETECT-UPLOAD] Redis Stream: {STREAM_KEY}")
    print(f"[FIRE-DETECT-UPLOAD] Image save dir: {IMAGE_SAVE_DIR}")
    yield

    close_redis_client()


app = FastAPI(title="Fire Detection Upload Receiver", lifespan=lifespan)

Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=[r"^/metrics$"]
).instrument(app).expose(
    app,
    endpoint="/metrics",
    include_in_schema=False
)

@app.get("/health")
def health():
    redis_ok = False
    redis_client = get_redis_client()
    if redis_client is not None:
        try:
            redis_ok = bool(redis_client.ping())
        except Exception:
            redis_ok = False

    # ---------------------- 테스트 부분 ----------------------
  

    return {
        "ok": True,
        "redis_connected": redis_ok,
        "stream_key": STREAM_KEY,
        "heatmap_stream_key": HEATMAP_STREAM_KEY,
        "image_save_dir": IMAGE_SAVE_DIR,
        "heatmap_image_save_dir": HEATMAP_IMAGE_SAVE_DIR,
        "max_upload_bytes": MAX_UPLOAD_BYTES,
    }

@app.post("/heatmap/upload")
async def upload_heatmap_image(
    request: Request,
    image_0: UploadFile | None = File(None, alias="image_0"),
    image_1: UploadFile | None = File(None, alias="image_1"),
    image_2: UploadFile | None = File(None, alias="image_2"),
    image_3: UploadFile | None = File(None, alias="image_3"),
    image_4: UploadFile | None = File(None, alias="image_4"),
    image_5: UploadFile | None = File(None, alias="image_5"),
    meta_json: str | None = Form(None, examples=[""]),
):
    try:
        data = json.loads(meta_json or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="meta_json must be valid JSON") from exc

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="meta_json must be a JSON object")

    x_min = data.get("x_min")
    x_max = data.get("x_max")
    y_min = data.get("y_min")
    y_max = data.get("y_max")
    lat = data.get("lat")
    lon = data.get("lon")
    radius_km = data.get("radius_km")
    num_times = data.get("num_times")
    opacity = data.get("opacity", 0.35)

    if any(value is None or value == "" for value in (x_min, x_max, y_min, y_max)):
        raise HTTPException(status_code=400, detail="x_min, x_max, y_min, y_max are required")

    print(data)

    heatmap_id = safe_id(str(data.get("heatmap_id") or f"heatmap-{int(time.time() * 1000)}"))
    Path(HEATMAP_IMAGE_SAVE_DIR).mkdir(parents=True, exist_ok=True)

    heatmap_images = [
        ("image_0", image_0),
        ("image_1", image_1),
        ("image_2", image_2),
        ("image_3", image_3),
        ("image_4", image_4),
        ("image_5", image_5),
    ]
    uploaded_images = [(field_name, upload) for field_name, upload in heatmap_images if upload is not None]
    if not uploaded_images:
        raise HTTPException(status_code=400, detail="at least one heatmap image is required")

    saved_images = []
    for frame_index, (field_name, upload) in enumerate(uploaded_images):
        image_ext = normalize_image_format(None, upload.filename, upload.content_type)
        image_name = f"{heatmap_id}_frame_{frame_index:03d}.{image_ext}"
        image_path = Path(HEATMAP_IMAGE_SAVE_DIR) / image_name

        image_size_bytes = await save_upload_file(upload, image_path)
        if image_size_bytes <= 0:
            image_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=f"{field_name} is empty")

        saved_images.append(
            {
                "field_name": field_name,
                "frame_index": frame_index,
                "image_name": image_name,
                "image_path": str(image_path),
                "image_size_bytes": image_size_bytes,
                "original_filename": upload.filename,
                "content_type": upload.content_type,
                "prediction_minutes": (frame_index + 1) * 10,
                "label": f"{(frame_index + 1) * 10}분 뒤 확산 예측 히트맵",
            }
        )

    client_host = request.client.host if request.client else None
    coordinates = {
        "bottom_left": {"x": x_min, "y": y_min},
        "top_right": {"x": x_max, "y": y_max},
    }
    payload = {
        "event_type": "heatmap_uploaded",
        "received_at": now_str(),
        "heatmap_id": heatmap_id,
        "image_count": len(saved_images),
        "frames": saved_images,
        "coordinates": coordinates,
        "opacity": opacity,
        "src_ip": client_host,
        "metadata": {
            "x_min": x_min,
            "x_max": x_max,
            "y_min": y_min,
            "y_max": y_max,
            "lat": lat,
            "lon": lon,
            "radius_km": radius_km,
            "num_times": num_times,
        },
    }
    msg_id = publish_completed_event(payload, HEATMAP_STREAM_KEY)
    print(
        "[HEATMAP-UPLOAD] images saved: "
        f"heatmap_id={heatmap_id} count={len(saved_images)} stream_id={msg_id}"
    )

    for saved_image in saved_images:
        image_path = saved_image["image_path"]
        img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)

        if img is None:
            raise HTTPException(status_code=400, detail=f"failed to read {saved_image['field_name']}")

        if len(img.shape) == 3 and img.shape[2] == 4:
            # 이미 알파 채널(4채널)이 있는 PNG라면 그대로 사용
            rgba = img.copy()
        else:
            # 알파 채널이 없는 일반 PNG(또는 JPG)라면 알파 채널 추가
            rgba = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)

        # 3. 검은색 픽셀 조건 (R, G, B가 모두 10 이하)
        # 이미 투명한 부분은 건드리지 않고, 검은색 픽셀만 찾습니다.

        black_pixels = np.where(
            (rgba[:, :, 2] <= 120)
        )

        # 4. 검은색 픽셀의 투명도(Alpha)를 0(완전 투명)으로 변경
        rgba[black_pixels] = [0, 0, 0, 0]

        # 5. 결과 저장
        cv2.imwrite(image_path, rgba)

    return {
        "ok": True,
        "id": msg_id,
        "stream_key": HEATMAP_STREAM_KEY,
        "heatmap_id": heatmap_id,
        "image_count": len(saved_images),
        "images": saved_images,
        "coordinates": coordinates,
        "opacity": opacity,
        "src_ip": client_host,
        "metadata": {
            "x_min": x_min,
            "x_max": x_max,
            "y_min": y_min,
            "y_max": y_max,
            "lat": lat,
            "lon": lon,
            "radius_km": radius_km,
            "num_times": num_times,
        },
    }

@app.post("/fire-detections/upload")
async def upload_fire_detection(
    request: Request,
    rgb_image: UploadFile | None = File(None, alias="RGB_image"),
    ir_image: UploadFile | None = File(None, alias="IR_image"),
    metadata: str | None = Form(None),
    event_id: str | None = Form(None, examples=["fire-test-001"]),
    image_id: str | None = Form(None, examples=["img-test-001"]),
    captured_at: str | None = Form(None, examples=["2026-04-28T12:30:00"]),
    lat: str | None = Form(None, examples=["37.5665"]),
    lon: str | None = Form(None, examples=["126.9780"]),
    alt: str | None = Form(None, examples=["120.5"]),
    confidence: str | None = Form(None, examples=["0.92"]),
    # system_id: str | None = Form(None, examples=["1"]),
    image_format: str | None = Form(None, examples=["jpg"]),
    logger = Depends(get_logger)
):
    logger.info("[backend]: upload api called") # extra 매개변수
    # logger.exception()

    metadata_dic = json.loads(metadata)

    try: 
        gps = metadata_dic.get("gps")
        detection = metadata_dic.get("detection")   
        # detection 
        # # {'objects': [{'class': 'Smoke', 'conf': 0.5803520083427429, 'bbox': [241, 0, 157, 45]}, {'class': 'Fire', 'conf': 0.3345894515514374, 'bbox': [284, 35, 70, 23]}]}
        system_id = metadata_dic.get("system_id")

        # captured_at = first_value(captured_at, normalize_captured_at(metadata_dic.get("timestamp")))
        captured_at = metadata_dic.get("timestamp")

        lat = gps.get("Latitude") 
        lon = gps.get("Longitude") 

        # alt = first_value(alt, metadata_value(gps, "Altitude", "altitude", "alt"))
        alt = gps.get("Altitude")

        objs = detection.get("objects")

        confidence = None

        for obj in objs:
            if obj["class"] == "fire":
                confidence = obj["conf"]

        if confidence == None:
            # raise Exception()       
            pass

    except Exception as e:
        logger.exception()

    if rgb_image is None:
        raise HTTPException(status_code=400, detail="RGB_image file is required")

    # try:
    #     confidence = max(float(detection.get("objects")[0].get("conf")), float(detection.get("objects")[1].get("conf")))
    # except Exception as e:
    #     confidence = detection.get("objects")[0].get("conf")

    # 요청으로 받은 이미지 형식을 허용된 확장자로 정규화한다.
    image_ext = normalize_image_format(image_format, rgb_image.filename, rgb_image.content_type)
    # event_id와 image_id가 없으면 테스트용 ID를 생성하고, 파일명에 안전한 형태로 정리한다.
    normalized_event_id = safe_id(event_id or f"fire-{int(time.time() * 1000)}")
    normalized_image_id = safe_id(image_id or uuid.uuid4().hex[:12])
    # 이벤트 ID와 이미지 ID를 조합해서 저장할 이미지 파일명을 만든다.
    image_name = f"{normalized_event_id}_{normalized_image_id}.{image_ext}"
    # 컨테이너 내부 이미지 저장 경로를 만든다.
    image_path = Path(IMAGE_SAVE_DIR) / image_name

    # --------------------------------------------------------

    if ir_image is None:
        raise HTTPException(status_code=400, detail="uploaded image is empty")


    ir_image_ext = normalize_image_format(image_format, ir_image.filename, ir_image.content_type)
    ir_image_name = f"{normalized_event_id}_{normalized_image_id}_ir.{ir_image_ext}"
    ir_image_path = Path(IR_IMAGE_SAVE_DIR) / ir_image_name
    
    # 업로드된 이미지를 로컬 공유 볼륨에 저장한다.
    image_size_bytes = await save_upload_file(rgb_image, image_path)
    ir_image_size_bytes = await save_upload_file(ir_image, ir_image_path)

    # 여기 나중에 save_upload_file 함수 내부로 옮길지 검토
    if image_size_bytes <= 0:
        # unlink는 pathlib.Path 객체에서 파일을 삭제하는 메서드
        # missing_ok=True는 파일이 이미 없어도 에러를 내지 말라는 의미
        image_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="uploaded image is empty")
    
    if ir_image_size_bytes <= 0:
        ir_image_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="uploaded image is empty")

    # --------------------------------------------------------

    # 요청을 보낸 클라이언트 IP를 payload에 남긴다.
    client_host = request.client.host if request.client else None

    # Redis Stream에 넣을 payload(FireDetectListener가 처리)
    payload = {
        "received_at": now_str(),
        "event_id": normalized_event_id,
        "image_id": normalized_image_id,
        "captured_at": captured_at,
        "lat": lat,
        "lon": lon,
        "alt": alt,
        "confidence": confidence,
        "system_id": system_id,
        "image_format": image_ext,
        "image_name": image_name,
        "image_path": str(image_path),
        "image_size_bytes": image_size_bytes,
        "src_ip": client_host,
        "upload_method": "http_multipart",
        "original_filename": rgb_image.filename,
        "content_type": rgb_image.content_type,
    }
    # 이미지 저장 완료 이벤트를 Redis Stream에 발행한다.
    msg_id = publish_completed_event(payload)

    # TCP 코드
    max_retries = 3

    for attempt in range(1, max_retries + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
                client_socket.settimeout(5)
                client_socket.connect(("192.168.0.31", 50000))

                # lat = 36.693575
                # lon = 126.580372 

                # client_socket.connect(("192.168.1.127", 50000))
                # client_socket.sendall(data)

                message = {
                    "lat": lat,
                    "lon": lon
                }

                # JSON 문자열 + 개행 문자
                data = json.dumps(message) + "\n"
                data = data.encode("utf-8")
                client_socket.sendall(data)
            break
        except Exception as e:
            print(e)

            if attempt == max_retries:
                print("failed")

    # 업로드 요청을 보낸 클라이언트에게 처리 결과를 반환한다.
    return {
        "ok": True,
        "id": msg_id,
        "stream_key": STREAM_KEY,
        "event_id": normalized_event_id,
        "image_id": normalized_image_id,
        "image_name": image_name,
        "image_size_bytes": image_size_bytes,
    }


if __name__ == "__main__":
    uvicorn.run("fastapi_image_upload:app", host=HTTP_HOST, port=HTTP_PORT)

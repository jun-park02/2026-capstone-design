import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import redis
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile


# Redis 서버 주소
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
# Redis 서버 포트
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
# 업로드 완료 이벤트를 발행할 Redis Stream 키
STREAM_KEY = os.getenv("STREAM_KEY", "fire_detect")
# 업로드된 이미지를 저장할 컨테이너 내부 경로
IMAGE_SAVE_DIR = os.getenv("IMG_SAVE_DIR", "/app/images")
# FastAPI 업로드 서버가 바인딩할 주소
HTTP_HOST = os.getenv("HTTP_HOST", "0.0.0.0")
# FastAPI 업로드 서버가 바인딩할 포트
HTTP_PORT = int(os.getenv("HTTP_PORT", "8000"))
# 허용할 최대 이미지 업로드 크기
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
# 업로드를 허용할 이미지 확장자 목록
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


redis_client: redis.Redis | None = None


def create_redis_client() -> redis.Redis:
    client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=0,
        decode_responses=True,
        socket_connect_timeout=5,
    )
    client.ping()
    print(f"[FIRE-DETECT-UPLOAD] Redis connected: {REDIS_HOST}:{REDIS_PORT}")
    return client


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    try:
        redis_client = create_redis_client()
    except Exception as exc:
        redis_client = None
        print(f"[FIRE-DETECT-UPLOAD] Redis connection failed: {exc}")

    Path(IMAGE_SAVE_DIR).mkdir(parents=True, exist_ok=True)
    print(f"[FIRE-DETECT-UPLOAD] HTTP upload server: {HTTP_HOST}:{HTTP_PORT}")
    print(f"[FIRE-DETECT-UPLOAD] Redis Stream: {STREAM_KEY}")
    print(f"[FIRE-DETECT-UPLOAD] Image save dir: {IMAGE_SAVE_DIR}")
    yield

    if redis_client:
        redis_client.close()


app = FastAPI(title="Fire Detection Upload Receiver", lifespan=lifespan)


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def normalize_image_format(value: Any, filename: str | None = None, content_type: str | None = None) -> str:
    # form-data의 image_format 값을 먼저 사용하고, 앞의 점과 대소문자를 정리한다.
    image_format = str(value or "").strip().lower().lstrip(".")
    # image_format이 없으면 업로드 파일명 확장자에서 이미지 형식을 추출한다.
    if not image_format and filename:
        image_format = Path(filename).suffix.lower().lstrip(".")
    # 파일명에서도 얻지 못하면 Content-Type 값에서 이미지 형식을 추출한다.
    if not image_format and content_type:
        image_format = content_type.split("/")[-1].lower()
    # jpeg와 jpg는 같은 형식으로 취급하기 위해 jpg로 통일한다.
    if image_format == "jpeg":
        image_format = "jpg"
    # 허용하지 않는 이미지 형식이면 요청을 거절한다.
    if image_format not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported image format")
    return image_format


def safe_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value.strip())
    return cleaned[:80] or uuid.uuid4().hex


def first_value(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def parse_metadata(metadata: str | None) -> dict[str, Any]:
    if not metadata:
        return {}

    try:
        parsed = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="metadata must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="metadata must be a JSON object")
    return parsed


def metadata_value(source: Any, *keys: str) -> Any:
    if not isinstance(source, dict):
        return None

    for key in keys:
        value = source.get(key)
        if value is not None and value != "":
            return value
    return None


def normalize_captured_at(value: Any) -> Any:
    if value is None or value == "":
        return None

    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(value)))
    except (TypeError, ValueError):
        return str(value)


async def save_upload_file(upload: UploadFile, image_path: Path) -> int:
    size = 0
    with image_path.open("wb") as output:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                output.close()
                image_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="uploaded image is too large")
            output.write(chunk)
    return size


def require_redis_client() -> redis.Redis:
    global redis_client
    if redis_client is None:
        try:
            redis_client = create_redis_client()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc
    return redis_client


def publish_completed_event(payload: dict[str, Any]) -> str:
    client = require_redis_client()
    try:
        msg_id = client.xadd(
            STREAM_KEY,
            {"payload": json.dumps(payload, ensure_ascii=False)},
            maxlen=10000,
            approximate=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis publish failed: {exc}") from exc

    print(
        "[FIRE-DETECT-UPLOAD] Redis event published: "
        f"id={msg_id} event_id={payload['event_id']} image={payload['image_name']}"
    )
    return str(msg_id)


@app.get("/health")
def health():
    redis_ok = False
    if redis_client is not None:
        try:
            redis_ok = bool(redis_client.ping())
        except Exception:
            redis_ok = False

    return {
        "ok": True,
        "redis_connected": redis_ok,
        "stream_key": STREAM_KEY,
        "image_save_dir": IMAGE_SAVE_DIR,
        "max_upload_bytes": MAX_UPLOAD_BYTES,
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
    system_id: str | None = Form(None, examples=["1"]),
    image_format: str | None = Form(None, examples=["jpg"]),
):
    print(rgb_image)

    metadata_obj = parse_metadata(metadata)
    gps = metadata_obj.get("gps")
    detection = metadata_obj.get("detection")
    if rgb_image is None:
        raise HTTPException(status_code=400, detail="RGB_image file is required")

    captured_at = first_value(captured_at, normalize_captured_at(metadata_obj.get("timestamp")))

    lat = gps.get("Latitude") if type(gps) is not str else 0
    lon = gps.get("Longitude") if type(gps) is not str else 0
    alt = first_value(alt, metadata_value(gps, "Altitude", "altitude", "alt"))
    
    confidence = first_value(confidence, metadata_value(detection, "confidence", "Confidence", "score", "Score"))

    # 요청으로 받은 이미지 형식을 허용된 확장자로 정규화한다.
    image_ext = normalize_image_format(image_format, rgb_image.filename, rgb_image.content_type)
    # event_id와 image_id가 없으면 테스트용 ID를 생성하고, 파일명에 안전한 형태로 정리한다.
    normalized_event_id = safe_id(event_id or f"fire-{int(time.time() * 1000)}")
    normalized_image_id = safe_id(image_id or uuid.uuid4().hex[:12])
    # 이벤트 ID와 이미지 ID를 조합해서 저장할 이미지 파일명을 만든다.
    image_name = f"{normalized_event_id}_{normalized_image_id}.{image_ext}"
    # 컨테이너 내부 이미지 저장 경로를 만든다.
    image_path = Path(IMAGE_SAVE_DIR) / image_name

    # 업로드된 이미지를 로컬 공유 볼륨에 저장한다.
    image_size_bytes = await save_upload_file(rgb_image, image_path)
    if image_size_bytes <= 0:
        image_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="uploaded image is empty")

    # 요청을 보낸 클라이언트 IP를 payload에 남긴다.
    client_host = request.client.host if request.client else None
    # 백엔드 FireDetectListener가 처리할 수 있도록 Redis Stream에 넣을 payload를 만든다.
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

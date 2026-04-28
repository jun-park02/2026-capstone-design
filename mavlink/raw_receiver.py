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


REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
STREAM_KEY = os.getenv("STREAM_KEY", "fire_detect")
IMAGE_SAVE_DIR = os.getenv("IMG_SAVE_DIR", "/app/images")
HTTP_HOST = os.getenv("HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("HTTP_PORT", "8000"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
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
    image_format = str(value or "").strip().lower().lstrip(".")
    if not image_format and filename:
        image_format = Path(filename).suffix.lower().lstrip(".")
    if not image_format and content_type:
        image_format = content_type.split("/")[-1].lower()
    if image_format == "jpeg":
        image_format = "jpg"
    if image_format not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported image format")
    return image_format


def safe_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value.strip())
    return cleaned[:80] or uuid.uuid4().hex


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
    image: UploadFile = File(...),
    event_id: str | None = Form(None),
    image_id: str | None = Form(None),
    captured_at: str | None = Form(None),
    lat: str | None = Form(None),
    lon: str | None = Form(None),
    alt: str | None = Form(None),
    confidence: str | None = Form(None),
    image_format: str | None = Form(None),
):
    image_ext = normalize_image_format(image_format, image.filename, image.content_type)
    normalized_event_id = safe_id(event_id or f"fire-{int(time.time() * 1000)}")
    normalized_image_id = safe_id(image_id or uuid.uuid4().hex[:12])
    image_name = f"{normalized_event_id}_{normalized_image_id}.{image_ext}"
    image_path = Path(IMAGE_SAVE_DIR) / image_name

    image_size_bytes = await save_upload_file(image, image_path)
    if image_size_bytes <= 0:
        image_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="uploaded image is empty")

    client_host = request.client.host if request.client else None
    client_port = request.client.port if request.client else None
    payload = {
        "received_at": now_str(),
        "event_id": normalized_event_id,
        "image_id": normalized_image_id,
        "captured_at": captured_at,
        "lat": lat,
        "lon": lon,
        "alt": alt,
        "confidence": confidence,
        "image_format": image_ext,
        "chunk_total": 1,
        "image_name": image_name,
        "image_path": str(image_path),
        "image_size_bytes": image_size_bytes,
        "src_ip": client_host,
        "src_port": client_port,
        "dst_port": HTTP_PORT,
        "upload_method": "http_multipart",
        "original_filename": image.filename,
        "content_type": image.content_type,
    }
    msg_id = publish_completed_event(payload)

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
    uvicorn.run("raw_receiver:app", host=HTTP_HOST, port=HTTP_PORT)

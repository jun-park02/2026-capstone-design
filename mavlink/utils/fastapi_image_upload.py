




import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import redis
from fastapi import HTTPException, UploadFile


REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
STREAM_KEY = os.getenv("STREAM_KEY", "fire_detect")
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
    # 업로드된 이미지를 지정된 경로에 바이너리 파일로 저장한다.
    with image_path.open("wb") as output:
        while True:
            # 메모리 사용을 줄이기 위해 1MB 단위로 나누어 읽는다.
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                # 허용 크기를 초과하면 저장 중인 파일을 닫고 삭제한다.
                output.close()
                image_path.unlink(missing_ok=True) # unlink는 해당 경로의 파일을 삭제
                raise HTTPException(status_code=413, detail="uploaded image is too large")
            output.write(chunk)
    return size


def get_redis_client() -> redis.Redis | None:
    # 새 연결을 만들지 않고 현재 연결 객체를 반환한다.
    return redis_client


def close_redis_client() -> None:
    global redis_client
    if redis_client is not None:
        redis_client.close()
        redis_client = None


def require_redis_client() -> redis.Redis:
    global redis_client
    if redis_client is None:
        try:
            redis_client = create_redis_client()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc
    return redis_client


def publish_completed_event(payload: dict[str, Any], stream_key: str = STREAM_KEY) -> str:
    client = require_redis_client()
    try:
        msg_id = client.xadd(
            stream_key,
            {"payload": json.dumps(payload, ensure_ascii=False)}, 
            maxlen=10000,  # 스트림에 유지할 항목 수 제한
            approximate=True,  # 성능을 위해 제한 개수의 일시적 초과 허용
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis publish failed: {exc}") from exc

    print(
        "[FIRE-DETECT-UPLOAD] Redis event published: "
        f"stream={stream_key} id={msg_id} "
        f"event_id={payload.get('event_id') or payload.get('heatmap_id')} "
        f"image={payload.get('image_name') or payload.get('image_count')}"
    )
    return str(msg_id)

import json
import os
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.fire_detect_listener import FireDetectListener
from app.redis_consumer import RedisStreamConsumer


consumer: RedisStreamConsumer | None = None
redis_client: redis.Redis | None = None
fire_listener: FireDetectListener | None = None

RAW_IMAGE_DIR = os.getenv("RAW_IMAGE_DIR", "/app/images")
RAW_IMAGE_URL_PREFIX = os.getenv("RAW_IMAGE_URL_PREFIX", "/fire-images")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기 관리."""
    global consumer, redis_client, fire_listener

    consumer = RedisStreamConsumer(
        redis_host=os.getenv("REDIS_HOST", "redis"),
        redis_port=int(os.getenv("REDIS_PORT", "6379")),
        stream_key=os.getenv("STREAM_KEY", "mystream"),
        group=os.getenv("CONSUMER_GROUP", "mygroup"),
        consumer=None,
    )
    await consumer.start()

    redis_client = redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=0,
        decode_responses=True,
    )

    fire_listener = FireDetectListener(
        redis_client=redis_client,
        raw_image_dir=RAW_IMAGE_DIR,
        raw_image_url_prefix=RAW_IMAGE_URL_PREFIX,
        stream_key=os.getenv("RAW_STREAM_KEY", "fire_detect"),
        block_ms=int(os.getenv("FIRE_DETECT_BLOCK_MS", "5000")),
    )
    await fire_listener.start()
    print("백그라운드 태스크 시작됨")

    yield

    if fire_listener:
        await fire_listener.stop()
    if consumer:
        await consumer.stop()
    if redis_client:
        redis_client.close()
    print("백그라운드 태스크 중지됨")


app = FastAPI(lifespan=lifespan)
os.makedirs(RAW_IMAGE_DIR, exist_ok=True)
app.mount(RAW_IMAGE_URL_PREFIX, StaticFiles(directory=RAW_IMAGE_DIR), name="fire-images")


@app.get("/")
def root():
    return {"msg": "root"}


@app.get("/health")
def health():
    """헬스 체크."""
    return {
        "status": "healthy",
        "consumer_running": consumer.is_running if consumer else False,
        "consumer_name": consumer.consumer if consumer else None,
        "fire_listener_running": fire_listener.is_running if fire_listener else False,
        "last_fire_event_id": fire_listener.last_event_id if fire_listener else None,
    }


@app.get("/mavlink/latest")
def get_latest_mavlink_message():
    """Redis Streams에서 최신 MAVLink 메시지 1건 조회."""
    if not redis_client:
        return {"ok": False, "message": "Redis client not initialized"}

    stream_key = os.getenv("STREAM_KEY", "mystream")
    entries = redis_client.xrevrange(stream_key, count=1)
    if not entries:
        return {"ok": True, "message": "No messages in stream", "data": None}

    msg_id, fields = entries[0]
    payload_raw = fields.get("payload")
    payload = json.loads(payload_raw) if payload_raw else None

    if payload and isinstance(payload.get("data"), str):
        try:
            payload["data"] = json.loads(payload["data"])
        except json.JSONDecodeError:
            pass

    return {"ok": True, "stream_key": stream_key, "id": msg_id, "data": payload}


@app.get("/raw/latest")
def get_latest_raw_udp_message():
    """Redis Streams에서 최신 Raw UDP 메시지 1건 조회."""
    if not redis_client:
        return {"ok": False, "message": "Redis client not initialized"}

    stream_key = os.getenv("RAW_STREAM_KEY", "fire_detect")
    entries = redis_client.xrevrange(stream_key, count=1)
    if not entries:
        return {"ok": True, "message": "No messages in stream", "data": None}

    msg_id, fields = entries[0]
    payload_raw = fields.get("payload")
    payload = json.loads(payload_raw) if payload_raw else None
    image_url = fire_listener.build_image_url(payload) if fire_listener else None

    return {
        "ok": True,
        "stream_key": stream_key,
        "id": msg_id,
        "data": payload,
        "image_url": image_url,
    }


@app.get("/raw/latest/live")
def get_latest_raw_udp_message_live():
    """백그라운드 리스너가 마지막으로 감지한 화재 이벤트 조회."""
    if not fire_listener or not fire_listener.last_event:
        return {"ok": True, "message": "No live fire event yet", "data": None}
    return {"ok": True, **fire_listener.last_event}
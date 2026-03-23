import json
import os
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI

from app.fire_detect_listener import FireDetectListener
from app.redis_consumer import RedisStreamConsumer


redis_client: redis.Redis | None = None
consumer: RedisStreamConsumer | None = None
fire_listener: FireDetectListener | None = None
RAW_IMAGE_DIR = os.getenv("RAW_IMAGE_DIR", "/app/images")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global consumer, redis_client, fire_listener

    # MAVLink 텔레메트리 스트림 consumer 시작
    consumer = RedisStreamConsumer(
        redis_host=os.getenv("REDIS_HOST", "redis"),
        redis_port=int(os.getenv("REDIS_PORT", "6379")),
        stream_key=os.getenv("STREAM_KEY", "mystream"),
        group=os.getenv("CONSUMER_GROUP", "mygroup"),
        consumer=None,
    )
    await consumer.start()

    # 화재 감지 스트림은 최신 이벤트 조회용으로 별도 Redis 클라이언트를 쓴다.
    redis_client = redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=0,
        decode_responses=True,
    )

    # fire_detect 스트림을 계속 감시하면서 마지막 이벤트를 메모리에 캐시한다.
    fire_listener = FireDetectListener(
        redis_client=redis_client,
        raw_image_dir=RAW_IMAGE_DIR,
        stream_key=os.getenv("RAW_STREAM_KEY", "fire_detect"),
        block_ms=int(os.getenv("FIRE_DETECT_BLOCK_MS", "5000")),
    )
    await fire_listener.start()

    yield

    if fire_listener:
        await fire_listener.stop()
    if consumer:
        await consumer.stop()
    if redis_client:
        redis_client.close()


app = FastAPI(lifespan=lifespan)


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

    # Redis에는 payload가 문자열로 들어 있으므로 한 번 JSON 파싱이 필요하다.
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

    # Redis의 최신 fire_detect 이벤트를 그대로 보여준다.
    stream_key = os.getenv("RAW_STREAM_KEY", "fire_detect")
    entries = redis_client.xrevrange(stream_key, count=1)
    if not entries:
        return {"ok": True, "message": "No messages in stream", "data": None}

    msg_id, fields = entries[0]
    payload_raw = fields.get("payload")
    payload = json.loads(payload_raw) if payload_raw else None

    # 최신 Redis 이벤트가 이미 백그라운드 리스너에서 처리된 상태라면
    # S3 업로드/DB 저장 결과까지 포함된 캐시 값을 우선 반환한다.
    if fire_listener and fire_listener.last_event_id == msg_id and fire_listener.last_event:
        return {"ok": True, **fire_listener.last_event}

    return {
        "ok": True,
        "stream_key": stream_key,
        "id": msg_id,
        "data": payload,
        "s3_image_url": payload.get("s3_image_url") if payload else None,
    }


@app.get("/raw/latest/live")
def get_latest_raw_udp_message_live():
    """백그라운드 리스너가 마지막으로 감지한 화재 이벤트 조회."""
    if not fire_listener or not fire_listener.last_event:
        return {"ok": True, "message": "No live fire event yet", "data": None}
    # 메모리에 캐시된 값을 주기 때문에 가장 빠르게 최신 이벤트를 보여줄 수 있다.
    return {"ok": True, **fire_listener.last_event}

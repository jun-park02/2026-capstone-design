import json
import os

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import runtime
from app.api.v1.helpers import serialize_confirmation_meta
from app.db import get_db_session
from app.models import FireEvent


router = APIRouter(tags=["streams"])


@router.get("/mavlink/latest")
def get_latest_mavlink_message():
    """일반 MAVLink 스트림의 최신 메시지 1건을 조회한다."""
    if not runtime.redis_client:
        return {"ok": False, "message": "Redis client not initialized"}

    stream_key = os.getenv("STREAM_KEY", "mystream")
    entries = runtime.redis_client.xrevrange(stream_key, count=1)
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


@router.get("/raw/latest")
def get_latest_raw_udp_message(session: Session = Depends(get_db_session)):
    """화재 이미지 스트림의 최신 이벤트를 Redis 기준으로 조회한다."""
    if not runtime.redis_client:
        return {"ok": False, "message": "Redis client not initialized"}

    stream_key = os.getenv("RAW_STREAM_KEY", "fire_detect")
    entries = runtime.redis_client.xrevrange(stream_key, count=1)
    if not entries:
        return {"ok": True, "message": "No messages in stream", "data": None}

    msg_id, fields = entries[0]
    payload_raw = fields.get("payload")
    payload = json.loads(payload_raw) if payload_raw else None

    event = None
    if payload and payload.get("event_id"):
        event = session.scalar(select(FireEvent).where(FireEvent.event_id == str(payload["event_id"])))

    if runtime.fire_listener and runtime.fire_listener.last_event_id == msg_id and runtime.fire_listener.last_event:
        # 리스너가 이미 가공해 둔 최신 결과가 있으면 그 값을 우선 사용한다.
        response = {"ok": True, **runtime.fire_listener.last_event}
        data = response.get("data")
        if isinstance(data, dict) and event is not None:
            merged_data = dict(data)
            merged_data.update(serialize_confirmation_meta(event))
            response["data"] = merged_data
        return response

    payload_with_meta = dict(payload) if payload else None
    if payload_with_meta is not None and event is not None:
        # 캐시된 가공 결과가 없으면 DB의 사용자 확인 메타데이터만 덧붙여 반환한다.
        payload_with_meta.update(serialize_confirmation_meta(event))

    return {
        "ok": True,
        "stream_key": stream_key,
        "id": msg_id,
        "data": payload_with_meta,
        "s3_image_url": payload_with_meta.get("s3_image_url") if payload_with_meta else None,
    }


@router.get("/raw/latest/live")
def get_latest_raw_udp_message_live(session: Session = Depends(get_db_session)):
    """리스너 메모리 캐시에 있는 최신 화재 이벤트를 바로 반환한다."""
    if not runtime.fire_listener or not runtime.fire_listener.last_event:
        return {"ok": True, "message": "No live fire event yet", "data": None}

    response = {"ok": True, **runtime.fire_listener.last_event}
    data = response.get("data")
    if isinstance(data, dict) and data.get("event_id"):
        event = session.scalar(select(FireEvent).where(FireEvent.event_id == str(data["event_id"])))
        if event is not None:
            merged_data = dict(data)
            merged_data.update(serialize_confirmation_meta(event))
            response["data"] = merged_data
    return response

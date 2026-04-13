import json
import os
from contextlib import asynccontextmanager
from html import escape
from typing import Any

import redis
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.fire_confirmation import (
    apply_confirmation_decision,
    normalize_and_validate_emails,
    send_confirmation_emails_for_event,
)
from app.fire_detect_listener import FireDetectListener
from app.models import FireEvent, FireEventEmailNotification, NotificationRecipient
from app.redis_consumer import RedisStreamConsumer


redis_client: redis.Redis | None = None
consumer: RedisStreamConsumer | None = None
fire_listener: FireDetectListener | None = None
RAW_IMAGE_DIR = os.getenv("RAW_IMAGE_DIR", "/app/images")


class NotificationRecipientsRequest(BaseModel):
    emails: list[str] = Field(default_factory=list, min_length=1)


def _serialize_confirmation_meta(event: FireEvent | None) -> dict[str, Any]:
    if event is None:
        return {}
    return {
        "user_confirmation": event.user_confirmation,
        "user_confirmed_at": event.user_confirmed_at.isoformat() if event.user_confirmed_at else None,
        "user_confirmed_by_email": event.user_confirmed_by_email,
    }


def _render_confirmation_page(
    *,
    title: str,
    message: str,
    event: FireEvent | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    image_url = None
    if event is not None and isinstance(event.raw_payload, dict):
        image_url = event.raw_payload.get("s3_image_url")

    event_id = event.event_id if event is not None else "-"
    current_status = event.user_confirmation if event is not None else None
    current_status_text = current_status or "pending"
    image_block = ""
    if image_url:
        image_url_safe = escape(image_url, quote=True)
        image_block = f"""
      <p style="margin: 0 0 16px;">
        <img
          src="{image_url_safe}"
          alt="Fire detection image"
          style="max-width: 100%; height: auto; border: 1px solid #d0d7de; border-radius: 8px;"
        />
      </p>
      <p style="margin: 0;">Image link: <a href="{image_url_safe}">{image_url_safe}</a></p>
"""

    html = f"""
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)}</title>
  </head>
  <body style="margin: 0; background: #f5f7fb; font-family: Arial, sans-serif; color: #1f2937;">
    <div style="max-width: 720px; margin: 48px auto; padding: 0 20px;">
      <div style="background: #fff; border: 1px solid #dbe2ea; border-radius: 14px; padding: 28px;">
        <h1 style="margin: 0 0 12px; font-size: 28px;">{escape(title)}</h1>
        <p style="margin: 0 0 16px; line-height: 1.6;">{escape(message)}</p>
        <p style="margin: 0 0 8px;">Event ID: <strong>{escape(event_id)}</strong></p>
        <p style="margin: 0 0 20px;">Current status: <strong>{escape(current_status_text)}</strong></p>
{image_block}
      </div>
    </div>
  </body>
</html>
""".strip()
    return HTMLResponse(content=html, status_code=status_code)


def _sync_cached_confirmation(event: FireEvent) -> None:
    if not fire_listener or not fire_listener.last_event:
        return
    if fire_listener.last_event_id != event.redis_stream_id:
        return

    data = fire_listener.last_event.get("data")
    if not isinstance(data, dict):
        return

    updated_data = dict(data)
    updated_data.update(_serialize_confirmation_meta(event))
    fire_listener.last_event["data"] = updated_data


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 애플리케이션의 생명주기 동안 필요한 백그라운드 리소스를 초기화하고 정리하는 함수.

    서버 시작 시 Redis 스트림 컨슈머와 화재 감지 리스너를 시작하고,
    서버 종료 시 관련 리소스를 순서대로 종료한다.
    """
    global consumer, redis_client, fire_listener

    # MAVLink 메시지를 소비할 Redis 스트림 컨슈머를 생성하고 시작한다.
    consumer = RedisStreamConsumer(
        redis_host=os.getenv("REDIS_HOST", "redis"),
        redis_port=int(os.getenv("REDIS_PORT", "6379")),
        stream_key=os.getenv("STREAM_KEY", "mystream"),
        group=os.getenv("CONSUMER_GROUP", "mygroup"),
        consumer=None,
    )
    await consumer.start()

    # 앱 전역에서 사용할 Redis 클라이언트를 초기화한다.
    redis_client = redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=0,
        decode_responses=True,
    )

    # 화재 감지 스트림을 실시간으로 감시하는 리스너를 생성하고 시작한다.
    fire_listener = FireDetectListener(
        redis_client=redis_client,
        raw_image_dir=RAW_IMAGE_DIR,
        stream_key=os.getenv("RAW_STREAM_KEY", "fire_detect"),
        block_ms=int(os.getenv("FIRE_DETECT_BLOCK_MS", "5000")),
    )
    await fire_listener.start()

    # 여기서부터 앱이 실제 요청을 처리한다.
    yield

    # 서버 종료 시 시작했던 리소스를 정리한다.
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
    return {
        "status": "healthy",
        "consumer_running": consumer.is_running if consumer else False,
        "consumer_name": consumer.consumer if consumer else None,
        "fire_listener_running": fire_listener.is_running if fire_listener else False,
        "last_fire_event_id": fire_listener.last_event_id if fire_listener else None,
    }


@app.post("/notification-recipients")
def register_notification_recipients(
    request: NotificationRecipientsRequest,
    session: Session = Depends(get_db_session),
):
    """
    알림 수신자 이메일을 등록하고, 이미 존재하지만 비활성화된 수신자는 다시 활성화하는 엔드포인트
    요청 본문으로 {"emails": [...]} 형태의 이메일 주소 리스트를 받는다.
    """
    # 이메일을 먼저 정규화하고 형식이 잘못된 항목은 따로 모은다.
    emails, invalid_emails = normalize_and_validate_emails(request.emails)
    if invalid_emails:
        raise HTTPException(status_code=400, detail={"invalid_emails": invalid_emails})
    if not emails:
        raise HTTPException(status_code=400, detail="at least one valid email is required")

    # 처리 결과를 상태별로 나눠 응답에 담는다.
    created: list[str] = []
    reactivated: list[str] = []
    existing: list[str] = []

    # 각 이메일은 신규 등록, 기등록, 비활성 계정 재활성화 중 하나로 처리한다.
    for email in emails:
        recipient = session.scalar(select(NotificationRecipient).where(NotificationRecipient.email == email))
        if recipient is None:
            session.add(NotificationRecipient(email=email, is_active=True))
            created.append(email)
            continue
        if recipient.is_active:
            existing.append(email)
            continue
        recipient.is_active = True
        reactivated.append(email)

    # 변경 사항을 저장한 뒤 현재 활성 수신자 수를 다시 집계한다.
    session.commit()

    total_active = session.scalar(
        select(func.count())
        .select_from(NotificationRecipient)
        .where(NotificationRecipient.is_active.is_(True))
    )

    return {
        "ok": True,
        "created": created,
        "reactivated": reactivated,
        "existing": existing,
        "total_active": total_active,
    }


@app.get("/notification-recipients")
def list_notification_recipients(session: Session = Depends(get_db_session)):
    recipients = session.scalars(
        select(NotificationRecipient).order_by(NotificationRecipient.email)
    ).all()
    return {
        "ok": True,
        "count": len(recipients),
        "items": [
            {
                "email": recipient.email,
                "is_active": recipient.is_active,
                "created_at": recipient.created_at.isoformat() if recipient.created_at else None,
                "updated_at": recipient.updated_at.isoformat() if recipient.updated_at else None,
            }
            for recipient in recipients
        ],
    }


@app.get("/fire-events/confirm", response_class=HTMLResponse)
def confirm_fire_event(
    token: str = Query(...),
    decision: str = Query(...),
    session: Session = Depends(get_db_session),
):
    try:
        result = apply_confirmation_decision(session, token=token, decision=decision)
    except ValueError as exc:
        return _render_confirmation_page(title="Invalid confirmation link", message=str(exc), status_code=400)
    except LookupError as exc:
        return _render_confirmation_page(title="Confirmation not found", message=str(exc), status_code=404)

    event = result["event"]
    _sync_cached_confirmation(event)

    if result["status"] == "already_responded":
        return _render_confirmation_page(
            title="Link already used",
            message="This confirmation link has already been used for a response.",
            event=event,
            status_code=200,
        )

    if result["event_was_updated"]:
        decision_text = "confirmed as a real fire" if event.user_confirmation == "Y" else "marked as not a fire"
        return _render_confirmation_page(
            title="Confirmation saved",
            message=f"Your response was recorded. This event is now {decision_text}.",
            event=event,
            status_code=200,
        )

    return _render_confirmation_page(
        title="Response recorded",
        message=(
            "Your response was recorded, but this event had already been finalized "
            f"as {event.user_confirmation} by another recipient."
        ),
        event=event,
        status_code=200,
    )


@app.post("/fire-events/{event_id}/send-confirmation-emails")
def send_fire_event_confirmation_emails(
    event_id: str,
    force_resend: bool = Query(False),
    session: Session = Depends(get_db_session),
):
    event = session.scalar(select(FireEvent).where(FireEvent.event_id == event_id))
    if event is None:
        raise HTTPException(status_code=404, detail="fire event not found")

    result = send_confirmation_emails_for_event(session, event, force_resend=force_resend)
    return {"ok": True, "event_id": event.event_id, **result}


@app.get("/fire-events/suspected/count")
def get_suspected_fire_event_count(session: Session = Depends(get_db_session)):
    """
    화재 확인 메일이 발송되었지만 아직 사용자가 확정하지 않은 화재 이벤트 수를 조회한다.

    집계 기준:
    - FireEvent.user_confirmation 이 NULL 인 이벤트
    - 연결된 FireEventEmailNotification 중 sent_status 가 "sent" 인 메일이 1건 이상 존재하는 이벤트
    - 수신자가 여러 명이어도 같은 화재 이벤트는 1건으로 집계
    """
    suspected_count = session.scalar(
        # 메일 발송 대상이 여러 명일 수 있으므로 이벤트 PK 기준으로 중복 제거한다.
        select(func.count(func.distinct(FireEvent.id)))
        .select_from(FireEvent)
        .join(FireEventEmailNotification, FireEventEmailNotification.fire_event_id == FireEvent.id)
        .where(
            FireEvent.user_confirmation.is_(None),
            FireEventEmailNotification.sent_status == "sent",
        )
    ) or 0

    return {
        "ok": True,
        "suspected_fire_count": suspected_count,
    }


@app.get("/mavlink/latest")
def get_latest_mavlink_message():
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
def get_latest_raw_udp_message(session: Session = Depends(get_db_session)):
    if not redis_client:
        return {"ok": False, "message": "Redis client not initialized"}

    stream_key = os.getenv("RAW_STREAM_KEY", "fire_detect")
    entries = redis_client.xrevrange(stream_key, count=1)
    if not entries:
        return {"ok": True, "message": "No messages in stream", "data": None}

    msg_id, fields = entries[0]
    payload_raw = fields.get("payload")
    payload = json.loads(payload_raw) if payload_raw else None

    event = None
    if payload and payload.get("event_id"):
        event = session.scalar(select(FireEvent).where(FireEvent.event_id == str(payload["event_id"])))

    if fire_listener and fire_listener.last_event_id == msg_id and fire_listener.last_event:
        response = {"ok": True, **fire_listener.last_event}
        data = response.get("data")
        if isinstance(data, dict) and event is not None:
            merged_data = dict(data)
            merged_data.update(_serialize_confirmation_meta(event))
            response["data"] = merged_data
        return response

    payload_with_meta = dict(payload) if payload else None
    if payload_with_meta is not None and event is not None:
        payload_with_meta.update(_serialize_confirmation_meta(event))

    return {
        "ok": True,
        "stream_key": stream_key,
        "id": msg_id,
        "data": payload_with_meta,
        "s3_image_url": payload_with_meta.get("s3_image_url") if payload_with_meta else None,
    }


@app.get("/raw/latest/live")
def get_latest_raw_udp_message_live(session: Session = Depends(get_db_session)):
    if not fire_listener or not fire_listener.last_event:
        return {"ok": True, "message": "No live fire event yet", "data": None}

    response = {"ok": True, **fire_listener.last_event}
    data = response.get("data")
    if isinstance(data, dict) and data.get("event_id"):
        event = session.scalar(select(FireEvent).where(FireEvent.event_id == str(data["event_id"])))
        if event is not None:
            merged_data = dict(data)
            merged_data.update(_serialize_confirmation_meta(event))
            response["data"] = merged_data
    return response

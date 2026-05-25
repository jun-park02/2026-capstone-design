from datetime import UTC, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.helpers import render_confirmation_page, sync_cached_confirmation
from app.db import get_db_session
from app.fire_confirmation import apply_confirmation_decision, send_confirmation_emails_for_event
from app.models import DroneTelemetry, FireEvent, FireEventEmailNotification


router = APIRouter(tags=["fire-events"])


class FireEventStatusUpdate(BaseModel):
    status: str


def _day_bounds_utc(tz_offset_hours: int = 9) -> tuple[datetime, datetime, str]:
    tz = timezone(timedelta(hours=tz_offset_hours))
    today = datetime.now(UTC).astimezone(tz).date()
    start_local = datetime.combine(today, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(UTC).replace(tzinfo=None),
        end_local.astimezone(UTC).replace(tzinfo=None),
        today.isoformat(),
    )


def _serialize_datetime(value):
    return value.isoformat() if value is not None else None


def _to_float(value):
    return float(value) if value is not None else None


def _fire_event_status(event: FireEvent) -> str:
    if event.user_confirmation == "Y":
        return "fire_confirmed"
    if event.user_confirmation == "N":
        return "reviewed"
    return "pending"


def _status_to_confirmation(status: str) -> str | None:
    normalized = status.strip().lower()
    if normalized in {"확인됨", "confirmed", "fire_confirmed", "real_fire", "y"}:
        return "Y"
    if normalized in {"오탐지", "rejected", "reviewed", "false_positive", "n"}:
        return "N"
    if normalized in {"진행중", "pending", "in_progress"}:
        return None
    raise ValueError("status must be one of 진행중, 확인됨, 오탐지")


def _fire_image_url(event: FireEvent) -> str | None:
    if isinstance(event.raw_payload, dict):
        image_url = event.raw_payload.get("s3_image_url")
        return str(image_url) if image_url else None
    return None


def _detected_drone(event: FireEvent) -> dict:
    payload = event.raw_payload if isinstance(event.raw_payload, dict) else {}
    system_id = payload.get("system_id") or payload.get("src_system_id")
    return {
        "system_id": system_id,
        "src_ip": event.src_ip,
    }


def _serialize_fire_event_detail(event: FireEvent) -> dict:
    occurred_at = event.captured_at or event.received_at
    return {
        "event_id": event.event_id,
        "occurred_at": _serialize_datetime(occurred_at),
        "location": {
            "lat": _to_float(event.lat),
            "lon": _to_float(event.lon),
            "alt": _to_float(event.alt),
        },
        "detected_drone": _detected_drone(event),
        "confidence": _to_float(event.confidence),
        "image_url": _fire_image_url(event),
        "in_progress": event.user_confirmation is None,
    }


def _serialize_fire_event(event: FireEvent) -> dict:
    return {
        "event_id": event.event_id,
        "redis_stream_id": event.redis_stream_id,
        "status": _fire_event_status(event),
        "received_at": _serialize_datetime(event.received_at),
        "captured_at": _serialize_datetime(event.captured_at),
        "lat": _to_float(event.lat),
        "lon": _to_float(event.lon),
        "alt": _to_float(event.alt),
        "confidence": _to_float(event.confidence),
        "image_url": _fire_image_url(event),
        "user_confirmation": event.user_confirmation,
        "user_confirmed_at": _serialize_datetime(event.user_confirmed_at),
        "user_confirmed_by_email": event.user_confirmed_by_email,
    }


def _serialize_telemetry(row: DroneTelemetry) -> dict:
    return {
        "id": row.id,
        "redis_stream_id": row.redis_stream_id,
        "message_type": row.message_type,
        "system_id": row.system_id,
        "component_id": row.component_id,
        "telemetry_at": _serialize_datetime(row.telemetry_at),
        "lat": _to_float(row.lat),
        "lon": _to_float(row.lon),
        "alt": _to_float(row.alt),
        "relative_alt": _to_float(row.relative_alt),
        "heading": _to_float(row.heading),
        "time_boot_ms": row.time_boot_ms,
        "raw_payload": row.raw_payload,
    }


@router.get("/fire-events/confirm", response_class=HTMLResponse)
def confirm_fire_event(
    token: str = Query(...),
    decision: str = Query(...),
    session: Session = Depends(get_db_session),
):
    try:
        result = apply_confirmation_decision(session, token=token, decision=decision)
    except ValueError as exc:
        return render_confirmation_page(title="Invalid confirmation link", message=str(exc), status_code=400)
    except LookupError as exc:
        return render_confirmation_page(title="Confirmation not found", message=str(exc), status_code=404)

    event = result["event"]
    sync_cached_confirmation(event)

    if result["status"] == "already_responded":
        return render_confirmation_page(
            title="Link already used",
            message="This confirmation link has already been used for a response.",
            event=event,
            status_code=200,
        )

    if result["event_was_updated"]:
        decision_text = "confirmed as a real fire" if event.user_confirmation == "Y" else "marked as not a fire"
        return render_confirmation_page(
            title="Confirmation saved",
            message=f"Your response was recorded. This event is now {decision_text}.",
            event=event,
            status_code=200,
        )

    return render_confirmation_page(
        title="Response recorded",
        message=(
            "Your response was recorded, but this event had already been finalized "
            f"as {event.user_confirmation} by another recipient."
        ),
        event=event,
        status_code=200,
    )


@router.post("/fire-events/{event_id}/send-confirmation-emails")
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


@router.get("/fire-events")
def list_fire_events(
    limit: int = Query(100, ge=1, le=1000),
    confirmation: str = Query("all", pattern="^(all|pending|confirmed|rejected)$"),
    session: Session = Depends(get_db_session),
):
    """Return fire events for the frontend detail page."""
    stmt = select(FireEvent).order_by(FireEvent.received_at.desc(), FireEvent.id.desc()).limit(limit)
    if confirmation == "pending":
        stmt = stmt.where(FireEvent.user_confirmation.is_(None))
    elif confirmation == "confirmed":
        stmt = stmt.where(FireEvent.user_confirmation == "Y")
    elif confirmation == "rejected":
        stmt = stmt.where(FireEvent.user_confirmation == "N")

    events = session.scalars(stmt).all()
    return {
        "ok": True,
        "confirmation": confirmation,
        "count": len(events),
        "items": [_serialize_fire_event(event) for event in events],
    }


@router.get("/fire-events/pending")
def list_pending_fire_events(
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_db_session),
):
    """Return fire events waiting for review."""
    events = session.scalars(
        select(FireEvent)
        .where(FireEvent.user_confirmation.is_(None))
        .order_by(FireEvent.received_at.desc(), FireEvent.id.desc())
        .limit(limit)
    ).all()
    return {
        "ok": True,
        "status": "pending",
        "count": len(events),
        "items": [_serialize_fire_event(event) for event in events],
    }


@router.get("/fire-events/today/reviewed/count")
def get_today_reviewed_fire_event_count(
    tz_offset_hours: int = Query(9, ge=-12, le=14),
    session: Session = Depends(get_db_session),
):
    """Count today's reviewed non-fire events."""
    start_at, end_at, target_date = _day_bounds_utc(tz_offset_hours)
    count = session.scalar(
        select(func.count())
        .select_from(FireEvent)
        .where(
            FireEvent.received_at >= start_at,
            FireEvent.received_at < end_at,
            FireEvent.user_confirmation == "N",
        )
    ) or 0
    return {
        "ok": True,
        "date": target_date,
        "status": "reviewed",
        "count": count,
        "tz_offset_hours": tz_offset_hours,
    }


@router.get("/fire-events/today/fire-confirmed/count")
def get_today_fire_confirmed_event_count(
    tz_offset_hours: int = Query(9, ge=-12, le=14),
    session: Session = Depends(get_db_session),
):
    """Count today's confirmed fire events."""
    start_at, end_at, target_date = _day_bounds_utc(tz_offset_hours)
    count = session.scalar(
        select(func.count())
        .select_from(FireEvent)
        .where(
            FireEvent.received_at >= start_at,
            FireEvent.received_at < end_at,
            FireEvent.user_confirmation == "Y",
        )
    ) or 0
    return {
        "ok": True,
        "date": target_date,
        "status": "fire_confirmed",
        "count": count,
        "tz_offset_hours": tz_offset_hours,
    }


def _count_fire_events_between(
    session: Session,
    start_at: datetime,
    end_at: datetime,
    confirmed_only: bool = False,
) -> int:
    stmt = (
        select(func.count(FireEvent.id))
        .select_from(FireEvent)
        .where(FireEvent.received_at >= start_at, FireEvent.received_at < end_at)
    )
    if confirmed_only:
        stmt = stmt.where(FireEvent.user_confirmation == "Y")
    return session.scalar(stmt) or 0


@router.get(
    "/fire-events/recent-statistics",
    responses={
        200: {
            "description": "Recent fire detection statistics for year, month, and week windows.",
            "content": {
                "application/json": {
                    "example": {
                        "ok": True,
                        "evaluated_at": "2026-04-28T12:00:00Z",
                        "basis": {
                            "time_field": "received_at",
                            "actual_fire_condition": "user_confirmation == 'Y'",
                        },
                        "last_year": {
                            "label": "recent_365_days",
                            "start_at": "2025-04-28T12:00:00",
                            "end_at": "2026-04-28T12:00:00",
                            "total_detection_count": 120,
                        },
                        "last_month": {
                            "label": "recent_30_days",
                            "start_at": "2026-03-29T12:00:00",
                            "end_at": "2026-04-28T12:00:00",
                            "total_detection_count": 18,
                            "actual_fire_count": 5,
                        },
                        "last_week": {
                            "label": "recent_7_days",
                            "start_at": "2026-04-21T12:00:00",
                            "end_at": "2026-04-28T12:00:00",
                            "total_detection_count": 6,
                            "actual_fire_count": 2,
                        },
                    }
                }
            },
        }
    },
)
def get_recent_fire_statistics(session: Session = Depends(get_db_session)):
    """
    Return rolling fire event statistics in one response.

    - last_year: total detection count for the recent 365 days
    - last_month: total detection count and actual fire count for the recent 30 days
    - last_week: total detection count and actual fire count for the recent 7 days
    """
    evaluated_at = datetime.utcnow()
    windows = {
        "last_year": ("recent_365_days", evaluated_at - timedelta(days=365)),
        "last_month": ("recent_30_days", evaluated_at - timedelta(days=30)),
        "last_week": ("recent_7_days", evaluated_at - timedelta(days=7)),
    }

    last_year_label, last_year_start = windows["last_year"]
    last_month_label, last_month_start = windows["last_month"]
    last_week_label, last_week_start = windows["last_week"]

    return {
        "ok": True,
        "evaluated_at": evaluated_at.isoformat() + "Z",
        "basis": {
            "time_field": "received_at",
            "actual_fire_condition": "user_confirmation == 'Y'",
        },
        "last_year": {
            "label": last_year_label,
            "start_at": last_year_start.isoformat(),
            "end_at": evaluated_at.isoformat(),
            "total_detection_count": _count_fire_events_between(
                session=session,
                start_at=last_year_start,
                end_at=evaluated_at,
            ),
        },
        "last_month": {
            "label": last_month_label,
            "start_at": last_month_start.isoformat(),
            "end_at": evaluated_at.isoformat(),
            "total_detection_count": _count_fire_events_between(
                session=session,
                start_at=last_month_start,
                end_at=evaluated_at,
            ),
            "actual_fire_count": _count_fire_events_between(
                session=session,
                start_at=last_month_start,
                end_at=evaluated_at,
                confirmed_only=True,
            ),
        },
        "last_week": {
            "label": last_week_label,
            "start_at": last_week_start.isoformat(),
            "end_at": evaluated_at.isoformat(),
            "total_detection_count": _count_fire_events_between(
                session=session,
                start_at=last_week_start,
                end_at=evaluated_at,
            ),
            "actual_fire_count": _count_fire_events_between(
                session=session,
                start_at=last_week_start,
                end_at=evaluated_at,
                confirmed_only=True,
            ),
        },
    }


@router.get(
    "/fire-events/recent-year/actual-fire-ratio",
    responses={
        200: {
            "description": "Actual fire ratio among all detected fire events for the recent 365 days.",
            "content": {
                "application/json": {
                    "example": {
                        "ratio": 0.25,
                    }
                }
            },
        }
    },
)
def get_recent_year_actual_fire_ratio(session: Session = Depends(get_db_session)):
    """
    Return the recent 365-day ratio requested as:
    actual fire count / total detected fire count * 100.
    """
    evaluated_at = datetime.utcnow()
    start_at = evaluated_at - timedelta(days=365)
    total_detection_count = _count_fire_events_between(
        session=session,
        start_at=start_at,
        end_at=evaluated_at,
    )
    actual_fire_count = _count_fire_events_between(
        session=session,
        start_at=start_at,
        end_at=evaluated_at,
        confirmed_only=True,
    )
    ratio = actual_fire_count / total_detection_count if total_detection_count > 0 else 0

    return {"ratio": ratio}


@router.get("/fire-events/today/with-telemetry")
def list_today_fire_events_with_telemetry(
    system_id: int | None = Query(None, ge=1),
    telemetry_before_sec: int = Query(300, ge=0, le=86400),
    telemetry_after_sec: int = Query(0, ge=0, le=86400),
    telemetry_limit_per_event: int = Query(200, ge=1, le=2000),
    telemetry_message_type: str = Query("GLOBAL_POSITION_INT", min_length=1, max_length=64),
    tz_offset_hours: int = Query(9, ge=-12, le=14),
    session: Session = Depends(get_db_session),
):
    """Return today's fire events with telemetry around each fire timestamp."""
    start_at, end_at, target_date = _day_bounds_utc(tz_offset_hours)
    events = session.scalars(
        select(FireEvent)
        .where(FireEvent.received_at >= start_at, FireEvent.received_at < end_at)
        .order_by(FireEvent.received_at.desc(), FireEvent.id.desc())
    ).all()

    items = []
    for event in events:
        fire_at = event.captured_at or event.received_at
        telemetry_start = fire_at - timedelta(seconds=telemetry_before_sec)
        telemetry_end = fire_at + timedelta(seconds=telemetry_after_sec)
        stmt = (
            select(DroneTelemetry)
            .where(
                DroneTelemetry.telemetry_at >= telemetry_start,
                DroneTelemetry.telemetry_at <= telemetry_end,
                DroneTelemetry.message_type == telemetry_message_type,
            )
            .order_by(DroneTelemetry.telemetry_at.desc(), DroneTelemetry.id.desc())
            .limit(telemetry_limit_per_event)
        )
        if system_id is not None:
            stmt = stmt.where(DroneTelemetry.system_id == system_id)

        telemetry_rows = list(reversed(session.scalars(stmt).all()))
        latest_at_fire = None
        for row in reversed(telemetry_rows):
            if row.telemetry_at <= fire_at:
                latest_at_fire = row
                break

        items.append(
            {
                "fire_event": _serialize_fire_event(event),
                "fire_at": _serialize_datetime(fire_at),
                "telemetry_window": {
                    "start_at": _serialize_datetime(telemetry_start),
                    "end_at": _serialize_datetime(telemetry_end),
                    "before_sec": telemetry_before_sec,
                    "after_sec": telemetry_after_sec,
                    "message_type": telemetry_message_type,
                    "system_id": system_id,
                },
                "matched_telemetry": _serialize_telemetry(latest_at_fire) if latest_at_fire else None,
                "telemetry_count": len(telemetry_rows),
                "telemetry": [_serialize_telemetry(row) for row in telemetry_rows],
            }
        )

    return {
        "ok": True,
        "date": target_date,
        "count": len(items),
        "items": items,
    }


@router.get("/fire-events/suspected/count")
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


@router.get("/fire-events/confirmation-completed/count")
def get_confirmation_completed_fire_event_count(session: Session = Depends(get_db_session)):
    """
    화재 확인 메일이 발송되었고 사용자가 Y/N 중 하나로 확정을 완료한 화재 이벤트 수를 조회한다.

    집계 기준:
    - FireEvent.user_confirmation 이 NULL 이 아닌 이벤트
    - 연결된 FireEventEmailNotification 중 sent_status 가 "sent" 인 메일이 1건 이상 존재하는 이벤트
    - 수신자가 여러 명이어도 같은 화재 이벤트는 1건으로 집계
    """
    completed_count = session.scalar(
        # 메일 발송 대상이 여러 명일 수 있으므로 이벤트 PK 기준으로 중복 제거한다.
        select(func.count(func.distinct(FireEvent.id)))
        .select_from(FireEvent)
        .join(FireEventEmailNotification, FireEventEmailNotification.fire_event_id == FireEvent.id)
        .where(
            FireEvent.user_confirmation.is_not(None),
            FireEventEmailNotification.sent_status == "sent",
        )
    ) or 0

    return {
        "ok": True,
        "confirmation_completed_count": completed_count,
    }


@router.get("/fire-events/current-status")
def get_current_fire_event_status(
    window_minutes: int = Query(30, ge=1, le=1440),
    session: Session = Depends(get_db_session),
):
    """
    최근 일정 시간 동안의 화재 이벤트 상태를 정상/경고/위험 중 하나로 판정한다.

    1차 판정 규칙:
    - 최근 window_minutes 내에 사용자 확정 결과가 "Y" 인 이벤트가 1건 이상이면 "위험"
    - 아니고 최근 window_minutes 내에 메일 발송 후 아직 미확정인 이벤트가 1건 이상이면 "경고"
    - 둘 다 없으면 "정상"
    """
    evaluated_at = datetime.utcnow()
    window_start = evaluated_at - timedelta(minutes=window_minutes)

    confirmed_fire_count = session.scalar(
        # 수신자가 여러 명이어도 같은 화재 이벤트는 1건으로 집계한다.
        select(func.count(func.distinct(FireEvent.id)))
        .select_from(FireEvent)
        .join(FireEventEmailNotification, FireEventEmailNotification.fire_event_id == FireEvent.id)
        .where(
            FireEvent.received_at >= window_start,
            FireEvent.user_confirmation == "Y",
            FireEventEmailNotification.sent_status == "sent",
        )
    ) or 0

    pending_suspected_count = session.scalar(
        # 확인 메일은 발송됐지만 아직 사용자 응답이 없는 이벤트만 집계한다.
        select(func.count(func.distinct(FireEvent.id)))
        .select_from(FireEvent)
        .join(FireEventEmailNotification, FireEventEmailNotification.fire_event_id == FireEvent.id)
        .where(
            FireEvent.received_at >= window_start,
            FireEvent.user_confirmation.is_(None),
            FireEventEmailNotification.sent_status == "sent",
        )
    ) or 0

    if confirmed_fire_count > 0:
        status = "위험"
        reason = f"최근 {window_minutes}분 내 실제 화재 확정 {confirmed_fire_count}건"
    elif pending_suspected_count > 0:
        status = "경고"
        reason = f"최근 {window_minutes}분 내 미확정 화재 의심 {pending_suspected_count}건"
    else:
        status = "정상"
        reason = f"최근 {window_minutes}분 내 확정 화재 및 미확정 의심 없음"

    return {
        "ok": True,
        "status": status,
        "reason": reason,
        "evaluated_at": evaluated_at.isoformat() + "Z",
        "metrics": {
            "confirmed_fire_count": confirmed_fire_count,
            "pending_suspected_count": pending_suspected_count,
        },
    }


@router.patch("/fire-events/{event_id}")
def update_fire_event_status(
    event_id: str,
    update: FireEventStatusUpdate,
    session: Session = Depends(get_db_session),
):
    try:
        confirmation = _status_to_confirmation(update.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    event = session.scalar(select(FireEvent).where(FireEvent.event_id == event_id))
    if event is None:
        raise HTTPException(status_code=404, detail="fire event not found")

    event.user_confirmation = confirmation
    if confirmation is None:
        event.user_confirmed_at = None
        event.user_confirmed_by_email = None
    else:
        event.user_confirmed_at = datetime.utcnow()
        event.user_confirmed_by_email = "dashboard"

    session.add(event)
    session.commit()
    session.refresh(event)
    sync_cached_confirmation(event)

    return {"ok": True, "item": _serialize_fire_event(event)}


@router.get(
    "/fire-events/{event_id}",
    responses={
        200: {
            "description": "Fire event detail.",
            "content": {
                "application/json": {
                    "example": {
                        "event_id": "fire-1714287600000",
                        "occurred_at": "2026-04-28T12:00:00",
                        "location": {
                            "lat": 37.5665,
                            "lon": 126.978,
                            "alt": 120.5,
                        },
                        "detected_drone": {
                            "system_id": 1,
                            "src_ip": "192.168.0.10",
                        },
                        "confidence": 0.92,
                        "image_url": "https://example-bucket.s3.amazonaws.com/fire/fire-1714287600000.jpg",
                        "in_progress": True,
                    }
                }
            },
        },
        404: {"description": "Fire event not found."},
    },
)
def get_fire_event_detail(
    event_id: str,
    session: Session = Depends(get_db_session),
):
    event = session.scalar(select(FireEvent).where(FireEvent.event_id == event_id))
    if event is None:
        raise HTTPException(status_code=404, detail="fire event not found")
    return _serialize_fire_event_detail(event)

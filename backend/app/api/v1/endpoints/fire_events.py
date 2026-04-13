from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.helpers import render_confirmation_page, sync_cached_confirmation
from app.db import get_db_session
from app.fire_confirmation import apply_confirmation_decision, send_confirmation_emails_for_event
from app.models import FireEvent, FireEventEmailNotification


router = APIRouter(tags=["fire-events"])


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

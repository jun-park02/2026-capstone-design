from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.fire_confirmation import normalize_and_validate_emails
from app.models import NotificationRecipient


router = APIRouter(tags=["notification-recipients"])

REGISTER_NOTIFICATION_RECIPIENTS_RESPONSES = {
    200: {
        "description": "Notification recipients registration result",
        "content": {
            "application/json": {
                "example": {
                    "ok": True,
                    "created": ["new@example.com"],
                    "reactivated": ["inactive@example.com"],
                    "existing": ["already@example.com"],
                    "total_active": 3,
                }
            }
        },
    },
    400: {
        "description": "Invalid email request",
        "content": {
            "application/json": {
                "examples": {
                    "invalidEmails": {
                        "summary": "Invalid email values",
                        "value": {
                            "detail": {
                                "invalid_emails": ["not-an-email"]
                            }
                        },
                    },
                    "emptyValidEmailList": {
                        "summary": "No valid email values",
                        "value": {
                            "detail": "at least one valid email is required"
                        },
                    },
                }
            }
        },
    },
}

UPDATE_NOTIFICATION_RECIPIENT_RESPONSES = {
    200: {
        "description": "Updated notification recipient",
        "content": {
            "application/json": {
                "example": {
                    "email": "somefakes@naver.com",
                    "is_active": False,
                    "created_at": "2026-04-28T10:07:15.919552",
                }
            }
        },
    },
    404: {
        "description": "Notification recipient not found",
        "content": {
            "application/json": {
                "example": {
                    "detail": "notification recipient not found"
                }
            }
        },
    },
}

DELETE_NOTIFICATION_RECIPIENT_RESPONSES = {
    204: {
        "description": "Notification recipient deleted. No response body is returned.",
    },
    404: {
        "description": "Notification recipient not found",
        "content": {
            "application/json": {
                "example": {
                    "detail": "notification recipient not found"
                }
            }
        },
    },
}


class NotificationRecipientsRequest(BaseModel):
    emails: list[str] = Field(default_factory=list, min_length=1)


class NotificationRecipientStatusRequest(BaseModel):
    is_active: bool


def _serialize_notification_recipient(recipient: NotificationRecipient) -> dict[str, object]:
    return {
        "email": recipient.email,
        "is_active": recipient.is_active,
        "created_at": recipient.created_at.isoformat() if recipient.created_at else None,
    }


@router.post(
    "/notification-recipients",
    responses=REGISTER_NOTIFICATION_RECIPIENTS_RESPONSES,
)
def register_notification_recipients(
    request: NotificationRecipientsRequest,
    session: Session = Depends(get_db_session),
):
    """
    알림 수신자 이메일을 등록하고, 이미 존재하지만 비활성화된 수신자는 다시 활성화하는 엔드포인트
    요청 본문으로 {"emails": [...]} 형태의 이메일 주소 리스트를 받는다.
    """
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


@router.get("/notification-recipients")
def list_notification_recipients(session: Session = Depends(get_db_session)):
    recipients = session.scalars(
        select(NotificationRecipient).order_by(NotificationRecipient.email)
    ).all()
    return [_serialize_notification_recipient(recipient) for recipient in recipients]


@router.patch(
    "/notification-recipients/{email}",
    responses=UPDATE_NOTIFICATION_RECIPIENT_RESPONSES,
)
def update_notification_recipient(
    email: str,
    request: NotificationRecipientStatusRequest,
    session: Session = Depends(get_db_session),
):
    recipient = session.scalar(
        select(NotificationRecipient).where(NotificationRecipient.email == email)
    )
    if recipient is None:
        raise HTTPException(status_code=404, detail="notification recipient not found")

    recipient.is_active = request.is_active
    session.commit()
    session.refresh(recipient)
    return _serialize_notification_recipient(recipient)


@router.delete(
    "/notification-recipients/{email}",
    status_code=204,
    responses=DELETE_NOTIFICATION_RECIPIENT_RESPONSES,
)
def delete_notification_recipient(
    email: str,
    session: Session = Depends(get_db_session),
):
    recipient = session.scalar(
        select(NotificationRecipient).where(NotificationRecipient.email == email)
    )
    if recipient is None:
        raise HTTPException(status_code=404, detail="notification recipient not found")

    session.delete(recipient)
    session.commit()

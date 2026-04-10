import hashlib
import os
import re
import secrets
import smtplib
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from html import escape
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FireEvent, FireEventEmailNotification, NotificationRecipient

EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
KST = ZoneInfo("Asia/Seoul")


def normalize_email_address(email: str) -> str:
    return email.strip().lower()


def is_valid_email_address(email: str) -> bool:
    _, parsed = parseaddr(email)
    return parsed == email and bool(EMAIL_PATTERN.fullmatch(email))


def normalize_and_validate_emails(emails: list[str]) -> tuple[list[str], list[str]]:
    normalized: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()

    for raw_email in emails:
        email = normalize_email_address(raw_email)
        if not email or not is_valid_email_address(email):
            invalid.append(raw_email)
            continue
        if email in seen:
            continue
        seen.add(email)
        normalized.append(email)

    return normalized, invalid


def generate_confirmation_token() -> str:
    return secrets.token_urlsafe(32)


def hash_confirmation_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _env_flag(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _display_value(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def _display_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")


@dataclass(slots=True)
class GmailSettings:
    smtp_host: str
    smtp_port: int
    username: str | None
    app_password: str | None
    from_email: str | None
    from_name: str
    confirm_base_url: str | None
    use_tls: bool


class FireConfirmationMailer:
    def __init__(self, settings: GmailSettings):
        self.settings = settings

    @classmethod
    def from_env(cls) -> "FireConfirmationMailer":
        username = os.getenv("GMAIL_USERNAME")
        settings = GmailSettings(
            smtp_host=os.getenv("GMAIL_SMTP_HOST", "smtp.gmail.com"),
            smtp_port=int(os.getenv("GMAIL_SMTP_PORT", "587")),
            username=username,
            app_password=os.getenv("GMAIL_APP_PASSWORD"),
            from_email=os.getenv("GMAIL_FROM_EMAIL", username or ""),
            from_name=os.getenv("GMAIL_FROM_NAME", "Fire Detect"),
            confirm_base_url=os.getenv("FIRE_CONFIRM_BASE_URL") or os.getenv("APP_BASE_URL"),
            use_tls=_env_flag("GMAIL_USE_TLS", True),
        )
        return cls(settings)

    def missing_configuration_reason(self) -> str | None:
        if not self.settings.username:
            return "GMAIL_USERNAME is not configured"
        if not self.settings.app_password:
            return "GMAIL_APP_PASSWORD is not configured"
        if not self.settings.from_email:
            return "GMAIL_FROM_EMAIL is not configured"
        if not self.settings.confirm_base_url:
            return "FIRE_CONFIRM_BASE_URL is not configured"
        return None

    def is_ready(self) -> bool:
        return self.missing_configuration_reason() is None

    def _build_confirmation_link(self, token: str, decision: str) -> str:
        base_url = self.settings.confirm_base_url.rstrip("/")
        return f"{base_url}/fire-events/confirm?token={quote(token, safe='')}&decision={decision}"

    def send_fire_confirmation_email(
        self,
        *,
        recipient_email: str,
        event: FireEvent,
        image_url: str,
        token: str,
    ) -> None:
        reason = self.missing_configuration_reason()
        if reason:
            raise RuntimeError(reason)

        yes_link = self._build_confirmation_link(token, "Y")
        no_link = self._build_confirmation_link(token, "N")
        image_url_safe = escape(image_url, quote=True)

        subject = f"[Fire Detect] {event.event_id}"
        text_body = "\n".join(
            [
                "Fire event confirmation requested.",
                "",
                f"Event ID: {event.event_id}",
                f"Captured at: {_display_datetime(event.captured_at)}",
                f"Confidence: {_display_value(event.confidence)}",
                f"Latitude: {_display_value(event.lat)}",
                f"Longitude: {_display_value(event.lon)}",
                f"Image URL: {image_url}",
                "",
                f"Confirm fire (Y): {yes_link}",
                f"Not a fire (N): {no_link}",
            ]
        )

        html_body = f"""
<html>
  <body style="font-family: Arial, sans-serif; color: #222;">
    <h2 style="margin-bottom: 12px;">Fire event confirmation requested</h2>
    <p style="margin: 0 0 8px;">Event ID: <strong>{escape(event.event_id)}</strong></p>
    <p style="margin: 0 0 8px;">Captured at: {_display_datetime(event.captured_at)}</p>
    <p style="margin: 0 0 8px;">Confidence: {_display_value(event.confidence)}</p>
    <p style="margin: 0 0 8px;">Latitude: {_display_value(event.lat)}</p>
    <p style="margin: 0 0 16px;">Longitude: {_display_value(event.lon)}</p>
    <p style="margin: 0 0 12px;">이미지를 확인하고 화재 확정 버튼을 눌러주세요.</p>
    <p style="margin: 0 0 16px;">
      <img
        src="{image_url_safe}"
        alt="Fire detection image"
        style="max-width: 100%; height: auto; border: 1px solid #d0d7de; border-radius: 8px;"
      />
    </p>
    <p style="margin: 0 0 16px;">
      <a
        href="{escape(yes_link, quote=True)}"
        style="display: inline-block; margin-right: 12px; padding: 10px 16px; background: #c2410c; color: #fff; text-decoration: none; border-radius: 6px;"
      >Confirm fire (Y)</a>
      <a
        href="{escape(no_link, quote=True)}"
        style="display: inline-block; padding: 10px 16px; background: #1f2937; color: #fff; text-decoration: none; border-radius: 6px;"
      >Not a fire (N)</a>
    </p>
    <p style="margin: 0;">이미지 링크: <a href="{image_url_safe}">{image_url_safe}</a></p>
  </body>
</html>
""".strip()

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((self.settings.from_name, self.settings.from_email))
        message["To"] = recipient_email
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as smtp:
            if self.settings.use_tls:
                smtp.starttls()
            smtp.login(self.settings.username, self.settings.app_password)
            smtp.send_message(message)


def send_confirmation_emails_for_event(
    session: Session,
    event: FireEvent,
    *,
    force_resend: bool = False,
) -> dict[str, Any]:
    recipients = session.scalars(
        select(NotificationRecipient)
        .where(NotificationRecipient.is_active.is_(True))
        .order_by(NotificationRecipient.id)
    ).all()
    if not recipients:
        return {
            "confirmation_email_status": "skipped",
            "confirmation_email_reason": "no_active_recipients",
            "confirmation_email_sent_count": 0,
        }

    raw_payload = event.raw_payload if isinstance(event.raw_payload, dict) else {}
    image_url = raw_payload.get("s3_image_url")
    if not image_url:
        return {
            "confirmation_email_status": "skipped",
            "confirmation_email_reason": "missing_s3_image_url",
            "confirmation_email_sent_count": 0,
        }

    mailer = FireConfirmationMailer.from_env()
    if not mailer.is_ready():
        return {
            "confirmation_email_status": "skipped",
            "confirmation_email_reason": mailer.missing_configuration_reason(),
            "confirmation_email_sent_count": 0,
        }

    sent_emails: list[str] = []
    skipped_emails: list[str] = []
    failed_emails: list[dict[str, str]] = []

    for recipient in recipients:
        notification = session.scalar(
            select(FireEventEmailNotification).where(
                FireEventEmailNotification.fire_event_id == event.id,
                FireEventEmailNotification.recipient_email == recipient.email,
            )
        )

        if notification is not None and notification.responded_at is not None:
            skipped_emails.append(recipient.email)
            continue
        if notification is not None and notification.sent_status == "sent" and not force_resend:
            skipped_emails.append(recipient.email)
            continue

        token = generate_confirmation_token()
        token_hash = hash_confirmation_token(token)

        if notification is None:
            notification = FireEventEmailNotification(
                fire_event_id=event.id,
                recipient_id=recipient.id,
                recipient_email=recipient.email,
                confirm_token_hash=token_hash,
            )
            session.add(notification)
        else:
            notification.recipient_id = recipient.id
            notification.recipient_email = recipient.email
            notification.confirm_token_hash = token_hash
            notification.sent_status = "pending"
            notification.send_error = None
            notification.sent_at = None

        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            failed_emails.append({"email": recipient.email, "error": f"DB token save failed: {exc}"})
            continue

        try:
            mailer.send_fire_confirmation_email(
                recipient_email=recipient.email,
                event=event,
                image_url=image_url,
                token=token,
            )
        except Exception as exc:
            failed_notification = session.get(FireEventEmailNotification, notification.id)
            if failed_notification is not None:
                failed_notification.sent_status = "failed"
                failed_notification.send_error = str(exc)
                try:
                    session.commit()
                except Exception:
                    session.rollback()
            failed_emails.append({"email": recipient.email, "error": str(exc)})
            continue

        sent_notification = session.get(FireEventEmailNotification, notification.id)
        if sent_notification is not None:
            sent_notification.sent_status = "sent"
            sent_notification.send_error = None
            sent_notification.sent_at = datetime.utcnow()
            try:
                session.commit()
            except Exception as exc:
                session.rollback()
                failed_emails.append(
                    {"email": recipient.email, "error": f"Email sent but status update failed: {exc}"}
                )
                continue

        sent_emails.append(recipient.email)

    if sent_emails and failed_emails:
        status = "partial"
    elif sent_emails:
        status = "sent"
    elif failed_emails:
        status = "failed"
    else:
        status = "skipped"

    return {
        "confirmation_email_status": status,
        "confirmation_email_reason": None if status != "skipped" else "already_sent_or_responded",
        "confirmation_email_sent_count": len(sent_emails),
        "confirmation_email_sent_to": sent_emails,
        "confirmation_email_skipped_to": skipped_emails,
        "confirmation_email_failed": failed_emails,
    }


def apply_confirmation_decision(
    session: Session,
    *,
    token: str,
    decision: str,
) -> dict[str, Any]:
    normalized_token = token.strip()
    normalized_decision = decision.strip().upper()
    if not normalized_token:
        raise ValueError("token is required")
    if normalized_decision not in {"Y", "N"}:
        raise ValueError("decision must be Y or N")

    notification = session.scalar(
        select(FireEventEmailNotification).where(
            FireEventEmailNotification.confirm_token_hash == hash_confirmation_token(normalized_token)
        ).with_for_update()
    )
    if notification is None:
        raise LookupError("confirmation token not found")

    event = session.scalar(
        select(FireEvent).where(FireEvent.id == notification.fire_event_id).with_for_update()
    )
    if event is None:
        raise LookupError("fire event not found for confirmation token")

    if notification.responded_at is not None:
        return {
            "status": "already_responded",
            "event": event,
            "notification": notification,
            "event_was_updated": False,
        }

    notification.decision = normalized_decision
    notification.responded_at = datetime.utcnow()

    event_was_already_confirmed = event.user_confirmation is not None
    event_was_updated = False
    if not event_was_already_confirmed:
        event.user_confirmation = normalized_decision
        event.user_confirmed_at = notification.responded_at
        event.user_confirmed_by_email = notification.recipient_email
        if isinstance(event.raw_payload, dict):
            raw_payload = dict(event.raw_payload)
            raw_payload["user_confirmation"] = normalized_decision
            raw_payload["user_confirmed_at"] = notification.responded_at.isoformat()
            raw_payload["user_confirmed_by_email"] = notification.recipient_email
            event.raw_payload = raw_payload
        event_was_updated = True

    session.commit()

    return {
        "status": "recorded",
        "event": event,
        "notification": notification,
        "event_was_updated": event_was_updated,
        "event_was_already_confirmed": event_was_already_confirmed,
    }

from html import escape
from typing import Any

from fastapi.responses import HTMLResponse

from app import runtime
from app.models import FireEvent


def serialize_confirmation_meta(event: FireEvent | None) -> dict[str, Any]:
    """화재 이벤트의 사용자 확인 상태 메타데이터를 응답용 dict로 변환한다."""
    if event is None:
        return {}
    return {
        "user_confirmation": event.user_confirmation,
        "user_confirmed_at": event.user_confirmed_at.isoformat() if event.user_confirmed_at else None,
        "user_confirmed_by_email": event.user_confirmed_by_email,
    }


def render_confirmation_page(
    *,
    title: str,
    message: str,
    event: FireEvent | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """확인 링크 클릭 결과를 보여주는 HTML 페이지를 생성한다."""
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


def sync_cached_confirmation(event: FireEvent) -> None:
    """최신 화재 이벤트 캐시에 사용자 확인 결과를 반영한다."""
    if not runtime.fire_listener or not runtime.fire_listener.last_event:
        return
    if runtime.fire_listener.last_event_id != event.redis_stream_id:
        return

    data = runtime.fire_listener.last_event.get("data")
    if not isinstance(data, dict):
        return

    updated_data = dict(data)
    updated_data.update(serialize_confirmation_meta(event))
    runtime.fire_listener.last_event["data"] = updated_data

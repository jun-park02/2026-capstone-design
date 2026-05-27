import os
import asyncio
import json
import time
from datetime import UTC, datetime, time as datetime_time, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import runtime
from app.db import SessionLocal, get_db_session
from app.models import DroneTelemetry


router = APIRouter(tags=["drones"])
router2 = APIRouter(tags=["SSE"])

DRONE_LAST_SEEN_KEY = os.getenv("DRONE_LAST_SEEN_KEY", "drone:last_seen")
DRONE_STATUS_KEY_PREFIX = os.getenv("DRONE_STATUS_KEY_PREFIX", "drone:status")
DRONE_PATH_IDS_KEY = os.getenv("DRONE_PATH_IDS_KEY", "drone:path:ids")
DRONE_PATH_KEY_PREFIX = os.getenv("DRONE_PATH_KEY_PREFIX", "drone:path")
DEFAULT_ACTIVE_TIMEOUT_SEC = int(os.getenv("DRONE_ACTIVE_TIMEOUT_SEC", "5"))
MAV_STATE_ACTIVE = 4
MAV_STATE_CRITICAL = 5
MAV_STATE_EMERGENCY = 6


def _drone_status_key(drone_id: str) -> str:
    return f"{DRONE_STATUS_KEY_PREFIX}:{drone_id}"


def _drone_path_key(drone_id: str) -> str:
    return f"{DRONE_PATH_KEY_PREFIX}:{drone_id}"


def _to_float(value):
    return float(value) if value is not None else None


def _serialize_datetime(value):
    return value.isoformat() if value is not None else None


def _day_bounds_utc(tz_offset_hours: int = 9) -> tuple[datetime, datetime, str]:
    tz = timezone(timedelta(hours=tz_offset_hours))
    today = datetime.now(UTC).astimezone(tz).date()
    start_local = datetime.combine(today, datetime_time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(UTC).replace(tzinfo=None),
        end_local.astimezone(UTC).replace(tzinfo=None),
        today.isoformat(),
    )


def _parse_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _sse_payload(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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


@router.get("/drones/active/count")
def get_active_drone_count(
    timeout_sec: int = Query(DEFAULT_ACTIVE_TIMEOUT_SEC, ge=1, le=3600),
):
    """
    최근 HEARTBEAT를 기준으로 active 상태인 드론 수를 조회한다.

    집계 기준:
    - timeout_sec 이내에 HEARTBEAT가 수신된 드론
    - 최근 HEARTBEAT의 system_status 가 MAV_STATE_ACTIVE 인 드론
    """
    if not runtime.redis_client:
        return {"ok": False, "message": "Redis client not initialized"}

    now_ts = time.time()
    threshold_ts = now_ts - timeout_sec
    candidate_ids = runtime.redis_client.zrangebyscore(DRONE_LAST_SEEN_KEY, threshold_ts, "+inf")

    if not candidate_ids:
        return {
            "ok": True,
            "active_drone_count": 0,
            "active_drone_ids": [],
            "timeout_sec": timeout_sec,
            "evaluated_at": datetime.now(UTC).isoformat(),
        }

    pipe = runtime.redis_client.pipeline()
    for drone_id in candidate_ids:
        pipe.hmget(_drone_status_key(drone_id), ["system_status", "last_seen_ts"])
    status_rows = pipe.execute()

    active_drone_ids: list[int | str] = []
    for drone_id, row in zip(candidate_ids, status_rows):
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            continue

        system_status_raw, last_seen_ts_raw = row
        if system_status_raw is None or last_seen_ts_raw is None:
            continue

        try:
            system_status = int(system_status_raw)
            last_seen_ts = float(last_seen_ts_raw)
        except (TypeError, ValueError):
            continue

        if system_status != MAV_STATE_ACTIVE:
            continue
        if last_seen_ts < threshold_ts:
            continue

        active_drone_ids.append(int(drone_id) if str(drone_id).isdigit() else drone_id)

    return {
        "ok": True,
        "active_drone_count": len(active_drone_ids),
        "active_drone_ids": active_drone_ids,
        "timeout_sec": timeout_sec,
        "evaluated_at": datetime.now(UTC).isoformat(),
    }


@router.get("/drones/telemetry")
def list_drone_telemetry(
    system_id: int | None = Query(None, ge=1),
    message_type: str | None = Query(None, min_length=1, max_length=64),
    limit: int = Query(100, ge=1, le=5000),
    session: Session = Depends(get_db_session),
):
    """Return persisted drone telemetry rows from MySQL."""
    stmt = select(DroneTelemetry).order_by(
        DroneTelemetry.telemetry_at.desc(),
        DroneTelemetry.id.desc(),
    )
    if system_id is not None:
        stmt = stmt.where(DroneTelemetry.system_id == system_id)
    if message_type:
        stmt = stmt.where(DroneTelemetry.message_type == message_type)

    rows = session.scalars(stmt.limit(limit)).all()
    return {
        "ok": True,
        "count": len(rows),
        "items": [{**_serialize_telemetry(row), "created_at": _serialize_datetime(row.created_at)} for row in rows],
    }


@router.get("/drones/messages/today")
def list_today_drone_warning_error_messages(
    severity: str = Query("warning,error", min_length=1),
    limit: int = Query(200, ge=1, le=5000),
    tz_offset_hours: int = Query(9, ge=-12, le=14),
    session: Session = Depends(get_db_session),
):
    """Return today's drone warning/error messages from persisted telemetry."""
    requested = {item.strip().lower() for item in severity.split(",") if item.strip()}
    start_at, end_at, target_date = _day_bounds_utc(tz_offset_hours)
    rows = session.scalars(
        select(DroneTelemetry)
        .where(
            DroneTelemetry.telemetry_at >= start_at,
            DroneTelemetry.telemetry_at < end_at,
            DroneTelemetry.message_type.in_(["STATUSTEXT", "HEARTBEAT"]),
        )
        .order_by(DroneTelemetry.telemetry_at.desc(), DroneTelemetry.id.desc())
        .limit(limit)
    ).all()

    items = []
    for row in rows:
        payload = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        data = _parse_json(payload.get("data"))
        data = data if isinstance(data, dict) else {}

        message_level = None
        message_text = None
        if row.message_type == "STATUSTEXT":
            mav_severity = data.get("severity")
            try:
                severity_value = int(mav_severity)
            except (TypeError, ValueError):
                severity_value = None

            if severity_value is not None and severity_value <= 3:
                message_level = "error"
            elif severity_value is not None and severity_value <= 4:
                message_level = "warning"
            message_text = data.get("text") or payload.get("text")
        elif row.message_type == "HEARTBEAT":
            try:
                system_status = int(data.get("system_status"))
            except (TypeError, ValueError):
                system_status = None
            if system_status == MAV_STATE_EMERGENCY:
                message_level = "error"
            elif system_status == MAV_STATE_CRITICAL:
                message_level = "warning"
            if message_level:
                message_text = data.get("system_status_name") or f"MAV_STATE={system_status}"

        if message_level is None or message_level not in requested:
            continue

        items.append(
            {
                "level": message_level,
                "message": message_text,
                "telemetry": _serialize_telemetry(row),
            }
        )

    return {
        "ok": True,
        "date": target_date,
        "severity": sorted(requested),
        "count": len(items),
        "items": items,
    }


def _latest_battery_rows(limit: int = 200) -> list[dict]:
    session = SessionLocal()
    try:
        rows = session.scalars(
            select(DroneTelemetry)
            .where(DroneTelemetry.message_type.in_(["SYS_STATUS", "BATTERY_STATUS"]))
            .order_by(DroneTelemetry.telemetry_at.desc(), DroneTelemetry.id.desc())
            .limit(limit)
        ).all()
        latest_by_drone: dict[str, dict] = {}
        for row in rows:
            drone_id = str(row.system_id) if row.system_id is not None else "unknown"
            if drone_id in latest_by_drone:
                continue

            payload = row.raw_payload if isinstance(row.raw_payload, dict) else {}
            data = _parse_json(payload.get("data"))
            data = data if isinstance(data, dict) else {}
            battery_remaining = data.get("battery_remaining")
            voltage_battery = data.get("voltage_battery")
            current_battery = data.get("current_battery")
            if battery_remaining is None and voltage_battery is None and current_battery is None:
                continue

            latest_by_drone[drone_id] = {
                "drone_id": drone_id,
                "system_id": row.system_id,
                "component_id": row.component_id,
                "message_type": row.message_type,
                "telemetry_at": _serialize_datetime(row.telemetry_at),
                "battery_remaining": battery_remaining,
                "voltage_battery": voltage_battery,
                "current_battery": current_battery,
                "raw_payload": row.raw_payload,
            }
        return sorted(latest_by_drone.values(), key=lambda item: item["drone_id"])
    finally:
        session.close()


def _latest_position_rows() -> list[dict]:
    if not runtime.redis_client:
        return []

    drone_ids = sorted(runtime.redis_client.smembers(DRONE_PATH_IDS_KEY))
    items = []
    for drone_id in drone_ids:
        entries = runtime.redis_client.lrange(_drone_path_key(drone_id), -1, -1)
        if not entries:
            continue
        point = _parse_json(entries[0])
        if not isinstance(point, dict):
            continue
        items.append(
            {
                "drone_id": str(drone_id),
                "system_id": point.get("system_id"),
                "component_id": point.get("component_id"),
                "telemetry_at": point.get("timestamp"),
                "lat": point.get("lat"),
                "lon": point.get("lon"),
                "alt": point.get("alt"),
                "relative_alt": point.get("relative_alt"),
                "heading": point.get("heading"),
                "position": point.get("position"),
                "stream_id": point.get("stream_id"),
            }
        )
    return items


@router2.get("/drones/battery/stream")
async def stream_drone_battery(
    request: Request,
    interval_sec: float = Query(2.0, ge=0.5, le=60),
):
    """Stream latest drone battery telemetry as Server-Sent Events."""

    async def event_generator():
        while not await request.is_disconnected():
            yield _sse_payload(
                "battery",
                {
                    "ok": True,
                    "items": _latest_battery_rows(),
                    "emitted_at": datetime.now(UTC).isoformat(),
                },
            )
            await asyncio.sleep(interval_sec)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router2.get("/drones/position/stream")
async def stream_drone_position(
    request: Request,
    interval_sec: float = Query(2.0, ge=0.5, le=60),
):
    """Stream latest drone positions as Server-Sent Events."""

    async def event_generator():
        while not await request.is_disconnected():
            yield _sse_payload(
                "position",
                {
                    "ok": True,
                    "items": _latest_position_rows(),
                    "emitted_at": datetime.now(UTC).isoformat(),
                },
            )
            await asyncio.sleep(interval_sec)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

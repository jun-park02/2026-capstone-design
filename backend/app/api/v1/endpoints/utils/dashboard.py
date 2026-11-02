from datetime import UTC, date, datetime, timezone, timedelta, time as datetime_time
from decimal import Decimal
import json
import os
import time as time_module
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app import app_state
from app.models import DashboardAggregate, DroneTelemetry, FireEvent, FireEventEmailNotification

DRONE_LAST_SEEN_KEY = os.getenv("DRONE_LAST_SEEN_KEY", "drone:last_seen")
DRONE_STATUS_KEY_PREFIX = os.getenv("DRONE_STATUS_KEY_PREFIX", "drone:status")
DRONE_PATH_IDS_KEY = os.getenv("DRONE_PATH_IDS_KEY", "drone:path:ids")
DRONE_PATH_KEY_PREFIX = os.getenv("DRONE_PATH_KEY_PREFIX", "drone:path")
DEFAULT_ACTIVE_TIMEOUT_SEC = int(os.getenv("DRONE_ACTIVE_TIMEOUT_SEC", "5"))
DEFAULT_MAP_CENTER = [37.5665, 126.9780]
MAV_STATE_ACTIVE = 4
MAV_STATE_CRITICAL = 5
MAV_STATE_EMERGENCY = 6


# 지정 시간대의 오늘 시작·종료 경계를 시간대 정보 없는 UTC 시각으로 변환하고, 해당 시간대의 오늘 날짜 문자열과 함께 반환한다.
def _day_bounds_utc() -> tuple[datetime, datetime]:
    # 현재 시간 구하기
    tz = timezone(timedelta(hours=9)) # print(tz)  # UTC+09:00
    today = datetime.now(tz).date() # print(today)  # 2026-11-01

    start_local = datetime.combine(today, datetime_time.min, tzinfo=tz) # 오늘 날짜와 자정 시각을 합침
    end_local = start_local + timedelta(days=1) # 오늘 시작 ~ 종료

    # DB의 naive UTC datetime과 비교하기 위해 UTC로 변환한 뒤 tzinfo를 제거한다.
    # 세 번째 값은 응답에 표시할 로컬 날짜 문자열이다.
    return (
        start_local.astimezone(UTC).replace(tzinfo=None),
        end_local.astimezone(UTC).replace(tzinfo=None),
        # today.isoformat(),
    )

def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _today_kst() -> date:
    return datetime.now(UTC).astimezone(timezone(timedelta(hours=9))).date()



def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value

    if value is None or value == "":
        return None

    text = str(value).strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _add_months(value: date, month_delta: int) -> date:
    month_index = value.year * 12 + value.month - 1 + month_delta
    return date(month_index // 12, month_index % 12 + 1, 1)


def _drone_status_key(drone_id: str) -> str:
    return f"{DRONE_STATUS_KEY_PREFIX}:{drone_id}"


def _drone_path_key(drone_id: str | int) -> str:
    return f"{DRONE_PATH_KEY_PREFIX}:{drone_id}"


def _drone_sort_key(drone_id: Any) -> tuple[int, int | str]:
    try:
        return (0, int(drone_id))
    except (TypeError, ValueError):
        return (1, str(drone_id))


def _serialize_aggregate(row: DashboardAggregate) -> dict:
    return {
        "id": row.id,
        "aggregate_date": row.aggregate_date.isoformat(),
        "metric_key": row.metric_key,
        "metric_value": float(row.metric_value),
        "metric_unit": row.metric_unit,
        "description": row.description,
        "extra": row.extra,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _count_fire_events_between(
    session: Session,
    *,
    start_at: datetime,
    end_at: datetime,
    confirmation: str | None = None,
    reviewed_only: bool = False,
) -> int:
    stmt = (
        select(func.count(FireEvent.id))
        .select_from(FireEvent)
        .where(FireEvent.received_at >= start_at, FireEvent.received_at < end_at)
    )
    if confirmation is not None:
        stmt = stmt.where(FireEvent.user_confirmation == confirmation)
    if reviewed_only:
        stmt = stmt.where(FireEvent.user_confirmation.is_not(None))
    return session.scalar(stmt) or 0


def _count_pending_suspected_events(session: Session) -> int:
    return session.scalar(
        select(func.count(func.distinct(FireEvent.id)))
        .select_from(FireEvent)
        .join(FireEventEmailNotification, FireEventEmailNotification.fire_event_id == FireEvent.id)
        .where(
            FireEvent.user_confirmation.is_(None),
            FireEventEmailNotification.sent_status == "sent",
        )
    ) or 0


def _dashboard_status(session: Session, *, window_minutes: int = 30) -> str:
    evaluated_at = datetime.utcnow()
    window_start = evaluated_at - timedelta(minutes=window_minutes)

    confirmed_fire_count = session.scalar(
        select(func.count(func.distinct(FireEvent.id)))
        .select_from(FireEvent)
        .join(FireEventEmailNotification, FireEventEmailNotification.fire_event_id == FireEvent.id)
        .where(
            FireEvent.received_at >= window_start,
            FireEvent.user_confirmation == "Y",
            FireEventEmailNotification.sent_status == "sent",
        )
    ) or 0
    if confirmed_fire_count > 0:
        return "위험"

    pending_suspected_count = session.scalar(
        select(func.count(func.distinct(FireEvent.id)))
        .select_from(FireEvent)
        .join(FireEventEmailNotification, FireEventEmailNotification.fire_event_id == FireEvent.id)
        .where(
            FireEvent.received_at >= window_start,
            FireEvent.user_confirmation.is_(None),
            FireEventEmailNotification.sent_status == "sent",
        )
    ) or 0
    if pending_suspected_count > 0:
        return "경고"

    return "정상"


def _average_delay_seconds(session: Session, *, start_at: datetime, end_at: datetime) -> float:
    rows = session.execute(
        select(FireEvent.captured_at, FireEvent.received_at).where(
            FireEvent.received_at >= start_at,
            FireEvent.received_at < end_at,
            FireEvent.captured_at.is_not(None),
        )
    ).all()
    delays = []
    for captured_at, received_at in rows:
        if captured_at is None or received_at is None:
            continue
        delay = (received_at - captured_at).total_seconds()
        if delay >= 0:
            delays.append(delay)
    if not delays:
        return 0.0
    return round(sum(delays) / len(delays), 1)


def _active_drone_count(timeout_sec: int = DEFAULT_ACTIVE_TIMEOUT_SEC) -> int:
    if not app_state.redis_client:
        return 0

    try:
        now_ts = time_module.time()
        threshold_ts = now_ts - timeout_sec
        candidate_ids = app_state.redis_client.zrangebyscore(DRONE_LAST_SEEN_KEY, threshold_ts, "+inf")
        if not candidate_ids:
            return 0

        pipe = app_state.redis_client.pipeline()
        for drone_id in candidate_ids:
            pipe.hmget(_drone_status_key(drone_id), ["system_status", "last_seen_ts"])
        status_rows = pipe.execute()

        active_count = 0
        for row in status_rows:
            if not isinstance(row, (list, tuple)) or len(row) != 2:
                continue
            system_status_raw, last_seen_ts_raw = row
            try:
                system_status = int(system_status_raw)
                last_seen_ts = float(last_seen_ts_raw)
            except (TypeError, ValueError):
                continue
            if system_status == MAV_STATE_ACTIVE and last_seen_ts >= threshold_ts:
                active_count += 1
        return active_count
    except Exception:
        return 0


def _drone_warning_error_count(session: Session, *, start_at: datetime, end_at: datetime) -> int:
    rows = session.scalars(
        select(DroneTelemetry)
        .where(
            DroneTelemetry.telemetry_at >= start_at,
            DroneTelemetry.telemetry_at < end_at,
            DroneTelemetry.message_type.in_(["STATUSTEXT", "HEARTBEAT"]),
        )
        .order_by(DroneTelemetry.telemetry_at.desc(), DroneTelemetry.id.desc())
        .limit(5000)
    ).all()

    count = 0
    for row in rows:
        payload = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        data = _parse_json(payload.get("data"))
        data = data if isinstance(data, dict) else {}

        if row.message_type == "STATUSTEXT":
            severity = _to_int(data.get("severity"))
            if severity is not None and severity <= 4:
                count += 1
        elif row.message_type == "HEARTBEAT":
            system_status = _to_int(data.get("system_status"))
            if system_status in {
                MAV_STATE_CRITICAL,
                MAV_STATE_EMERGENCY,
            }:
                count += 1
    return count


def _average_battery_percent(session: Session, *, recent_seconds: int = 15, limit: int = 500) -> float:
    threshold_at = datetime.utcnow() - timedelta(seconds=recent_seconds)
    rows = session.scalars(
        select(DroneTelemetry)
        .where(
            DroneTelemetry.telemetry_at >= threshold_at,
            DroneTelemetry.message_type.in_(["SYS_STATUS", "BATTERY_STATUS"]),
        )
        .order_by(DroneTelemetry.telemetry_at.desc(), DroneTelemetry.id.desc())
        .limit(limit)
    ).all()

    values = []
    seen_drones: set[str] = set()
    for row in rows:
        drone_id = str(row.system_id) if row.system_id is not None else "unknown"
        if drone_id in seen_drones:
            continue

        payload = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        data = _parse_json(payload.get("data"))
        data = data if isinstance(data, dict) else {}
        battery_remaining = _to_float(data.get("battery_remaining"))
        if battery_remaining is None or battery_remaining < 0:
            continue

        seen_drones.add(drone_id)
        values.append(battery_remaining)

    if not values:
        return 0.0
    return round(sum(values) / len(values), 1)


def _cached_drone_paths(*, recent_seconds: int = 15, point_limit: int = 200) -> list[dict[str, Any]]:
    if not app_state.redis_client:
        return []

    try:
        threshold_at = datetime.utcnow() - timedelta(seconds=recent_seconds)
        drone_ids = sorted(app_state.redis_client.smembers(DRONE_PATH_IDS_KEY), key=_drone_sort_key)
        paths = []
        for drone_id in drone_ids:
            entries = app_state.redis_client.lrange(_drone_path_key(drone_id), -point_limit, -1)
            points = []
            for entry in entries:
                point = _parse_json(entry)
                if not isinstance(point, dict):
                    continue
                point_at = _parse_datetime_or_none(point.get("telemetry_at") or point.get("timestamp"))
                if point_at is None or point_at < threshold_at:
                    continue
                lat = _to_float(point.get("lat"))
                lon = _to_float(point.get("lon"))
                if lat is None or lon is None:
                    position = point.get("position")
                    if isinstance(position, list) and len(position) == 2:
                        lat = _to_float(position[0])
                        lon = _to_float(position[1])
                if lat is None or lon is None:
                    continue
                points.append(
                    {
                        "lat": lat,
                        "lon": lon,
                        "alt": _to_float(point.get("alt")),
                        "position": [lat, lon],
                    }
                )
            if points:
                paths.append({"drone_id": str(drone_id), "path": points, "latest": points[-1]})
        return paths
    except Exception:
        return []


def _db_drone_paths(session: Session, *, recent_seconds: int = 15, point_limit: int = 200) -> list[dict[str, Any]]:
    threshold_at = datetime.utcnow() - timedelta(seconds=recent_seconds)
    rows = session.scalars(
        select(DroneTelemetry)
        .where(
            DroneTelemetry.telemetry_at >= threshold_at,
            DroneTelemetry.message_type == "GLOBAL_POSITION_INT",
            DroneTelemetry.lat.is_not(None),
            DroneTelemetry.lon.is_not(None),
        )
        .order_by(DroneTelemetry.telemetry_at.desc(), DroneTelemetry.id.desc())
        .limit(point_limit)
    ).all()

    if not rows:
        return []

    points_by_drone: dict[str, list[dict[str, Any]]] = {}
    for row in reversed(rows):
        drone_id = str(row.system_id) if row.system_id is not None else "unknown"
        lat = _to_float(row.lat)
        lon = _to_float(row.lon)
        if lat is None or lon is None:
            continue
        points_by_drone.setdefault(drone_id, []).append(
            {
                "lat": lat,
                "lon": lon,
                "alt": _to_float(row.alt),
                "position": [lat, lon],
            }
        )

    return [
        {"drone_id": drone_id, "path": points, "latest": points[-1]}
        for drone_id, points in sorted(points_by_drone.items(), key=lambda item: _drone_sort_key(item[0]))
        if points
    ]


def _dashboard_drone_paths(session: Session, *, recent_seconds: int = 15) -> list[dict[str, Any]]:
    cached_paths = _cached_drone_paths(recent_seconds=recent_seconds)
    if cached_paths:
        return cached_paths
    return _db_drone_paths(session, recent_seconds=recent_seconds)


def _recent_fire_positions(
    session: Session,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: int = 100,
) -> list[list[float]]:
    stmt = select(FireEvent).where(FireEvent.lat.is_not(None), FireEvent.lon.is_not(None))
    if start_at is not None:
        stmt = stmt.where(FireEvent.received_at >= start_at)
    if end_at is not None:
        stmt = stmt.where(FireEvent.received_at < end_at)

    events = session.scalars(
        stmt.order_by(FireEvent.received_at.desc(), FireEvent.id.desc()).limit(limit)
    ).all()

    positions = []
    for event in events:
        lat = _to_float(event.lat)
        lon = _to_float(event.lon)
        if lat is None or lon is None:
            continue
        positions.append([lat, lon])
    return positions


def _monthly_fire_data(session: Session, *, tz_offset_hours: int = 9) -> list[dict[str, Any]]:
    tz = timezone(timedelta(hours=tz_offset_hours))
    today = datetime.now(UTC).astimezone(tz).date()
    current_month = _month_start(today)
    months = [_add_months(current_month, offset) for offset in range(-11, 1)]
    counts = {month: 0 for month in months}

    start_local = datetime.combine(months[0], datetime_time.min, tzinfo=tz)
    start_at = start_local.astimezone(UTC).replace(tzinfo=None)
    rows = session.scalars(
        select(FireEvent.received_at).where(FireEvent.received_at >= start_at)
    ).all()
    for received_at in rows:
        received_month = _month_start(_as_utc(received_at).astimezone(tz).date())
        if received_month in counts:
            counts[received_month] += 1

    return [{"name": f"{month.month}월", "감지": counts[month]} for month in months]


def _weekly_fire_data(session: Session, *, tz_offset_hours: int = 9) -> list[dict[str, Any]]:
    tz = timezone(timedelta(hours=tz_offset_hours))
    today = datetime.now(UTC).astimezone(tz).date()
    days = [today - timedelta(days=6 - offset) for offset in range(7)]
    day_stats = {day: {"전체": 0, "실제": 0} for day in days}
    weekday_names = ["월", "화", "수", "목", "금", "토", "일"]

    start_local = datetime.combine(days[0], datetime_time.min, tzinfo=tz)
    end_local = datetime.combine(days[-1] + timedelta(days=1), datetime_time.min, tzinfo=tz)
    rows = session.execute(
        select(FireEvent.received_at, FireEvent.user_confirmation).where(
            FireEvent.received_at >= start_local.astimezone(UTC).replace(tzinfo=None),
            FireEvent.received_at < end_local.astimezone(UTC).replace(tzinfo=None),
        )
    ).all()
    for received_at, user_confirmation in rows:
        event_day = _as_utc(received_at).astimezone(tz).date()
        if event_day not in day_stats:
            continue
        day_stats[event_day]["전체"] += 1
        if user_confirmation == "Y":
            day_stats[event_day]["실제"] += 1

    return [
        {
            "name": weekday_names[day.weekday()],
            "전체": day_stats[day]["전체"],
            "실제": day_stats[day]["실제"],
        }
        for day in days
    ]

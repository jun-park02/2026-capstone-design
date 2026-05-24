import json
import os
import time as time_module
from datetime import UTC, date, datetime, time as datetime_time, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pymavlink import mavutil
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import runtime
from app.db import get_db_session
from app.models import DashboardAggregate, DroneTelemetry, FireEvent, FireEventEmailNotification


router = APIRouter(tags=["dashboard"])

DRONE_LAST_SEEN_KEY = os.getenv("DRONE_LAST_SEEN_KEY", "drone:last_seen")
DRONE_STATUS_KEY_PREFIX = os.getenv("DRONE_STATUS_KEY_PREFIX", "drone:status")
DRONE_PATH_IDS_KEY = os.getenv("DRONE_PATH_IDS_KEY", "drone:path:ids")
DRONE_PATH_KEY_PREFIX = os.getenv("DRONE_PATH_KEY_PREFIX", "drone:path")
DEFAULT_ACTIVE_TIMEOUT_SEC = int(os.getenv("DRONE_ACTIVE_TIMEOUT_SEC", "5"))
DEFAULT_MAP_CENTER = [37.5665, 126.9780]


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


def _day_bounds_utc(tz_offset_hours: int = 9) -> tuple[datetime, datetime, str]:
    # 기본값은 한국 시간(KST, UTC+9)이며, 해당 시간대 기준의 오늘 날짜를 구한다.
    tz = timezone(timedelta(hours=tz_offset_hours))
    today = datetime.now(UTC).astimezone(tz).date()

    # 로컬 시간대 기준 오늘 00:00부터 내일 00:00 직전까지를 하루 범위로 잡는다.
    start_local = datetime.combine(today, datetime_time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)

    # DB의 naive UTC datetime과 비교하기 위해 UTC로 변환한 뒤 tzinfo를 제거한다.
    # 세 번째 값은 응답에 표시할 로컬 날짜 문자열이다.
    return (
        start_local.astimezone(UTC).replace(tzinfo=None),
        end_local.astimezone(UTC).replace(tzinfo=None),
        today.isoformat(),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
    if not runtime.redis_client:
        return 0

    try:
        now_ts = time_module.time()
        threshold_ts = now_ts - timeout_sec
        candidate_ids = runtime.redis_client.zrangebyscore(DRONE_LAST_SEEN_KEY, threshold_ts, "+inf")
        if not candidate_ids:
            return 0

        pipe = runtime.redis_client.pipeline()
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
            if system_status == mavutil.mavlink.MAV_STATE_ACTIVE and last_seen_ts >= threshold_ts:
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
                mavutil.mavlink.MAV_STATE_CRITICAL,
                mavutil.mavlink.MAV_STATE_EMERGENCY,
            }:
                count += 1
    return count


def _average_battery_percent(session: Session, *, limit: int = 500) -> float:
    rows = session.scalars(
        select(DroneTelemetry)
        .where(DroneTelemetry.message_type.in_(["SYS_STATUS", "BATTERY_STATUS"]))
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


def _cached_drone_paths(point_limit: int = 200) -> list[dict[str, Any]]:
    if not runtime.redis_client:
        return []

    try:
        drone_ids = sorted(runtime.redis_client.smembers(DRONE_PATH_IDS_KEY), key=_drone_sort_key)
        paths = []
        for drone_id in drone_ids:
            entries = runtime.redis_client.lrange(_drone_path_key(drone_id), -point_limit, -1)
            points = []
            for entry in entries:
                point = _parse_json(entry)
                if not isinstance(point, dict):
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


def _db_drone_paths(session: Session, *, point_limit: int = 200) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(DroneTelemetry)
        .where(
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


def _dashboard_drone_paths(session: Session) -> list[dict[str, Any]]:
    cached_paths = _cached_drone_paths()
    if cached_paths:
        return cached_paths
    return _db_drone_paths(session)


def _recent_fire_positions(session: Session, *, limit: int = 100) -> list[list[float]]:
    events = session.scalars(
        select(FireEvent)
        .where(FireEvent.lat.is_not(None), FireEvent.lon.is_not(None))
        .order_by(FireEvent.received_at.desc(), FireEvent.id.desc())
        .limit(limit)
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


@router.get("/dashboard/summary")
def get_dashboard_summary(
    session: Session = Depends(get_db_session),
):
    """
    대시보드 화면이 필요로 하는 전체 응답 데이터를 한 번에 반환
    화재 이벤트 집계, 드론 상태, 최신 배터리 데이터, 지도 표시용 좌표를 함께 리턴
    """
    # 한국 시간(KST, UTC+9) 기준 집계 범위와 최근 30일 통계 기준 시점을 계산한다.
    today_start, today_end, target_date = _day_bounds_utc()
    evaluated_at = datetime.utcnow()
    recent_month_start = evaluated_at - timedelta(days=30)

    # 메일 발송 후 아직 확인되지 않은 의심 이벤트 수
    active_suspects = _count_pending_suspected_events(session)
    # 오늘 처리된 이벤트 수를 계산
    resolved_today = _count_fire_events_between(
        session=session,
        start_at=today_start,
        end_at=today_end,
        reviewed_only=True,
    )
    # 오늘 사용자 확인 결과가 실제 화재(Y)로 확정된 이벤트 수
    active_fires = _count_fire_events_between(
        session=session,
        start_at=today_start,
        end_at=today_end,
        confirmation="Y",
    )

    # 최근 30일 기준 전체 탐지, 실제 화재, 오탐지 건수를 계산한다.
    month_total = _count_fire_events_between(
        session=session,
        start_at=recent_month_start,
        end_at=evaluated_at,
    )
    month_real = _count_fire_events_between(
        session=session,
        start_at=recent_month_start,
        end_at=evaluated_at,
        confirmation="Y",
    )
    month_false_positive = _count_fire_events_between(
        session=session,
        start_at=recent_month_start,
        end_at=evaluated_at,
        confirmation="N",
    )

    # Redis 캐시나 DB에서 드론 경로를 가져오고, 첫 번째 드론을 대표 위치로 사용한다.
    drone_paths = _dashboard_drone_paths(session)
    primary_path = drone_paths[0]["path"] if drone_paths else []
    primary_latest = drone_paths[0]["latest"] if drone_paths else None
    if primary_latest:
        drone_lat = primary_latest["lat"]
        drone_lon = primary_latest["lon"]
        drone_alt = primary_latest.get("alt") or 0
    else:
        # 아직 드론 좌표가 없으면 기본 지도 중심 좌표로 대체한다.
        drone_lat, drone_lon = DEFAULT_MAP_CENTER
        drone_alt = 0

    # 최근 화재 위치 목록을 지도 마커로 사용하고, 없으면 드론 위치를 기본 화재 위치로 둔다.
    fire_locations = _recent_fire_positions(session)
    fire_location = fire_locations[0] if fire_locations else [drone_lat, drone_lon]

    # 프론트 대시보드 컴포넌트가 바로 사용할 수 있는 형태로 지표와 지도 데이터를 묶어 반환한다.
    return {
        "ok": True,
        "date": target_date,
        "evaluated_at": evaluated_at.isoformat() + "Z",
        "status": _dashboard_status(session),
        "activeSuspects": active_suspects,
        "resolvedToday": resolved_today,
        "activeFires": active_fires,
        "avgDelay": _average_delay_seconds(session, start_at=today_start, end_at=today_end),
        "activeDrones": _active_drone_count(),
        "errorCount": _drone_warning_error_count(session, start_at=today_start, end_at=today_end),
        "avgBattery": _average_battery_percent(session),
        "droneLocation": {
            "lat": drone_lat,
            "lng": drone_lon,
            "alt": drone_alt,
        },
        "yearlyData": _monthly_fire_data(session),
        "weeklyData": _weekly_fire_data(session),
        "pieData": [
            {"name": "실제 화재", "value": month_real},
            {"name": "오탐지", "value": month_false_positive},
        ],
        "dronePath": [point["position"] for point in primary_path],
        "fireLocation": fire_location,
        "fireLocations": fire_locations,
        "monthTotal": month_total,
        "monthReal": month_real,
    }


@router.get(
    "/dashboard/aggregates",
    responses={
        200: {
            "description": "Dashboard aggregate metrics for a date.",
            "content": {
                "application/json": {
                    "example": {
                        "ok": True,
                        "aggregate_date": "2026-04-28",
                        "count": 3,
                        "items": [
                            {
                                "id": 1,
                                "aggregate_date": "2026-04-28",
                                "metric_key": "total_fire_events",
                                "metric_value": 12.0,
                                "metric_unit": "count",
                                "description": "오늘 발생한 전체 화재 감지 이벤트 수",
                                "extra": None,
                                "created_at": "2026-04-28T00:00:00",
                                "updated_at": "2026-04-28T00:05:00",
                            },
                            {
                                "id": 2,
                                "aggregate_date": "2026-04-28",
                                "metric_key": "fire_confirmed_events",
                                "metric_value": 4.0,
                                "metric_unit": "count",
                                "description": "오늘 확정된 실제 화재 이벤트 수",
                                "extra": None,
                                "created_at": "2026-04-28T00:00:00",
                                "updated_at": "2026-04-28T00:05:00",
                            },
                            {
                                "id": 3,
                                "aggregate_date": "2026-04-28",
                                "metric_key": "active_drone_count",
                                "metric_value": 2.0,
                                "metric_unit": "count",
                                "description": "최근 기준 활성 드론 수",
                                "extra": {"timeout_sec": 60},
                                "created_at": "2026-04-28T00:00:00",
                                "updated_at": "2026-04-28T00:05:00",
                            },
                        ],
                    }
                }
            },
        }
    },
)
def list_dashboard_aggregates(
    aggregate_date: date | None = Query(None),
    metric_key: list[str] | None = Query(None),
    session: Session = Depends(get_db_session),
):
    """
    대시보드 집계 테이블에서 지정한 날짜의 지표 목록을 조회한다.

    aggregate_date가 없으면 한국 시간 기준 오늘 날짜를 사용하고,
    metric_key가 전달되면 해당 지표들만 필터링한다.

    dashboard_aggregates 집계 테이블에서 데이터를 가져옴.
    현재는 테이블에 집계가 저장되지 않음.
    """
    target_date = aggregate_date or _today_kst()
    stmt = (
        select(DashboardAggregate)
        .where(DashboardAggregate.aggregate_date == target_date)
        .order_by(DashboardAggregate.metric_key)
    )
    if metric_key:
        stmt = stmt.where(DashboardAggregate.metric_key.in_(metric_key))

    rows = session.scalars(stmt).all()
    return {
        "ok": True,
        "aggregate_date": target_date.isoformat(),
        "count": len(rows),
        "items": [_serialize_aggregate(row) for row in rows],
    }


@router.get(
    "/dashboard/aggregates/ratio",
    responses={
        200: {
            "description": "Ratio between two dashboard aggregate metrics.",
            "content": {
                "application/json": {
                    "example": {
                        "ok": True,
                        "aggregate_date": "2026-04-28",
                        "numerator": {
                            "id": 2,
                            "aggregate_date": "2026-04-28",
                            "metric_key": "fire_confirmed_events",
                            "metric_value": 4.0,
                            "metric_unit": "count",
                            "description": "Confirmed fire events today.",
                            "extra": None,
                            "created_at": "2026-04-28T00:00:00",
                            "updated_at": "2026-04-28T00:05:00",
                        },
                        "denominator": {
                            "id": 1,
                            "aggregate_date": "2026-04-28",
                            "metric_key": "total_fire_events",
                            "metric_value": 12.0,
                            "metric_unit": "count",
                            "description": "Total fire detection events today.",
                            "extra": None,
                            "created_at": "2026-04-28T00:00:00",
                            "updated_at": "2026-04-28T00:05:00",
                        },
                        "ratio": 0.3333333333333333,
                        "percentage": 33.33333333333333,
                    }
                }
            },
        }
    },
)
def get_dashboard_aggregate_ratio(
    numerator_key: str = Query(..., min_length=1, max_length=100),
    denominator_key: str = Query(..., min_length=1, max_length=100),
    aggregate_date: date | None = Query(None),
    session: Session = Depends(get_db_session),
):
    """
    대시보드 집계 테이블의 두 지표를 이용해 비율을 계산한다.

    numerator_key / denominator_key 값을 반환하고,
    프론트에서 바로 표시할 수 있도록 percentage 값도 함께 내려준다.

    프론트에서 “확정 화재 비율”, “정상 처리 비율”, “성공률” 같은 걸 표시할 때 쓰는 엔드포인트
    """
    target_date = aggregate_date or _today_kst()
    rows = session.scalars(
        select(DashboardAggregate).where(
            DashboardAggregate.aggregate_date == target_date,
            DashboardAggregate.metric_key.in_([numerator_key, denominator_key]),
        )
    ).all()
    by_key = {row.metric_key: row for row in rows}
    numerator = by_key.get(numerator_key)
    denominator = by_key.get(denominator_key)
    if numerator is None or denominator is None:
        raise HTTPException(status_code=404, detail="aggregate metric not found")
    if denominator.metric_value == 0:
        raise HTTPException(status_code=400, detail="denominator metric is zero")

    ratio = Decimal(numerator.metric_value) / Decimal(denominator.metric_value)
    return {
        "ok": True,
        "aggregate_date": target_date.isoformat(),
        "numerator": _serialize_aggregate(numerator),
        "denominator": _serialize_aggregate(denominator),
        "ratio": float(ratio),
        "percentage": float(ratio * Decimal("100")),
    }


@router.get("/dashboard/aggregates/{metric_key}")
def get_dashboard_aggregate(
    metric_key: str,
    aggregate_date: date | None = Query(None),
    session: Session = Depends(get_db_session),
):
    """
    대시보드 집계 테이블에서 지정한 날짜의 단일 지표를 조회한다.

    aggregate_date가 없으면 한국 시간 기준 오늘 날짜를 사용한다.
    """
    target_date = aggregate_date or _today_kst()
    row = session.scalar(
        select(DashboardAggregate).where(
            DashboardAggregate.aggregate_date == target_date,
            DashboardAggregate.metric_key == metric_key,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="aggregate metric not found")

    return {"ok": True, "item": _serialize_aggregate(row)}

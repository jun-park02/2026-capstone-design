import json
import os
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import runtime
from app.db import get_db_session
from app.models import DroneTelemetry, FireEvent


router = APIRouter(tags=["map"])

DEFAULT_DRONE_STREAM_KEY = os.getenv("STREAM_KEY", "drone_telemetry")
DRONE_PATH_IDS_KEY = os.getenv("DRONE_PATH_IDS_KEY", "drone:path:ids")
DRONE_PATH_KEY_PREFIX = os.getenv("DRONE_PATH_KEY_PREFIX", "drone:path")


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


def _normalize_coordinate(value: Any, *, max_abs: float, scale: float = 1e7) -> float | None:
    coordinate = _to_float(value)
    if coordinate is None:
        return None
    if abs(coordinate) > max_abs:
        coordinate = coordinate / scale
    if abs(coordinate) > max_abs:
        return None
    return coordinate


def _normalize_millimeters(value: Any) -> float | None:
    distance = _to_float(value)
    if distance is None:
        return None
    return distance / 1000


def _serialize_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _fire_status(event: FireEvent) -> str:
    if event.user_confirmation == "Y":
        return "confirmed"
    if event.user_confirmation == "N":
        return "rejected"
    return "pending"


def _event_image_url(event: FireEvent) -> str | None:
    if isinstance(event.raw_payload, dict):
        image_url = event.raw_payload.get("s3_image_url")
        return str(image_url) if image_url else None
    return None


def _build_drone_point(stream_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    data = _parse_json(payload.get("data"))
    if not isinstance(data, dict):
        return None

    message_type = payload.get("message_type") or data.get("mavpackettype")
    if message_type != "GLOBAL_POSITION_INT":
        return None

    lat = _normalize_coordinate(data.get("lat"), max_abs=90)
    lon = _normalize_coordinate(data.get("lon"), max_abs=180)
    if lat is None or lon is None:
        return None

    system_id = _to_int(payload.get("system_id"))
    component_id = _to_int(payload.get("component_id"))
    alt = _normalize_millimeters(data.get("alt"))
    relative_alt = _normalize_millimeters(data.get("relative_alt"))

    return {
        "stream_id": stream_id,
        "timestamp": payload.get("timestamp"),
        "system_id": system_id,
        "component_id": component_id,
        "lat": lat,
        "lon": lon,
        "alt": alt,
        "relative_alt": relative_alt,
        "position": [lat, lon],
        "heading": _to_float(data.get("hdg")),
        "time_boot_ms": _to_int(data.get("time_boot_ms")),
    }


def _drone_path_key(system_id: int | str) -> str:
    return f"{DRONE_PATH_KEY_PREFIX}:{system_id}"


def _drone_sort_key(drone_id: Any) -> tuple[int, int | str]:
    try:
        return (0, int(drone_id))
    except (TypeError, ValueError):
        return (1, str(drone_id))


def _format_drone_paths(paths_by_drone: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    drones = []
    for drone_path in paths_by_drone.values():
        path = drone_path["path"]
        latest = path[-1] if path else None
        drones.append(
            {
                **drone_path,
                "point_count": len(path),
                "positions": [point["position"] for point in path],
                "latest": latest,
            }
        )

    drones.sort(key=lambda drone: _drone_sort_key(drone["drone_id"]))
    return drones


def _get_cached_drone_paths(*, system_id: int | None, point_limit: int) -> list[dict[str, Any]]:
    if not runtime.redis_client:
        return []

    if system_id is not None:
        drone_ids = [str(system_id)]
    else:
        drone_ids = sorted(runtime.redis_client.smembers(DRONE_PATH_IDS_KEY), key=_drone_sort_key)

    paths_by_drone: dict[str, dict[str, Any]] = {}
    for drone_id in drone_ids:
        entries = runtime.redis_client.lrange(_drone_path_key(drone_id), -point_limit, -1)
        path: list[dict[str, Any]] = []
        for entry in entries:
            point = _parse_json(entry)
            if not isinstance(point, dict):
                continue

            position = point.get("position")
            if not isinstance(position, list) or len(position) != 2:
                lat = _to_float(point.get("lat"))
                lon = _to_float(point.get("lon"))
                if lat is None or lon is None:
                    continue
                point["position"] = [lat, lon]

            path.append(point)

        if not path:
            continue

        latest = path[-1]
        paths_by_drone[str(drone_id)] = {
            "drone_id": str(drone_id),
            "system_id": _to_int(latest.get("system_id")),
            "component_id": _to_int(latest.get("component_id")),
            "path": path,
        }

    return _format_drone_paths(paths_by_drone)


def _get_drone_paths(
    *,
    system_id: int | None,
    message_limit: int,
    point_limit: int,
    stream_key: str,
) -> dict[str, Any]:
    if not runtime.redis_client:
        return {
            "redis_available": False,
            "stream_key": stream_key,
            "message": "Redis client not initialized",
            "drones": [],
        }

    if stream_key == DEFAULT_DRONE_STREAM_KEY:
        cached_drones = _get_cached_drone_paths(system_id=system_id, point_limit=point_limit)
        if cached_drones:
            return {
                "redis_available": True,
                "stream_key": stream_key,
                "source": "cached_paths",
                "sampled_message_count": 0,
                "drones": cached_drones,
            }

    entries = runtime.redis_client.xrevrange(stream_key, count=message_limit)
    entries.reverse()

    paths_by_drone: dict[str, dict[str, Any]] = {}
    for stream_id, fields in entries:
        payload_raw = fields.get("payload") if isinstance(fields, dict) else None
        payload = _parse_json(payload_raw)
        if not isinstance(payload, dict):
            continue

        point = _build_drone_point(stream_id, payload)
        if point is None:
            continue
        if system_id is not None and point["system_id"] != system_id:
            continue

        drone_key = str(point["system_id"]) if point["system_id"] is not None else "unknown"
        drone_path = paths_by_drone.setdefault(
            drone_key,
            {
                "drone_id": drone_key,
                "system_id": point["system_id"],
                "component_id": point["component_id"],
                "path": [],
            },
        )
        drone_path["path"].append(point)
        if len(drone_path["path"]) > point_limit:
            drone_path["path"] = drone_path["path"][-point_limit:]

    return {
        "redis_available": True,
        "stream_key": stream_key,
        "source": "stream_scan",
        "sampled_message_count": len(entries),
        "drones": _format_drone_paths(paths_by_drone),
    }


def _get_latest_battery_by_drone(
    *,
    session: Session,
    system_id: int | None,
    limit: int = 500,
) -> dict[str, dict[str, Any]]:
    stmt = (
        select(DroneTelemetry)
        .where(DroneTelemetry.message_type.in_(["SYS_STATUS", "BATTERY_STATUS"]))
        .order_by(DroneTelemetry.telemetry_at.desc(), DroneTelemetry.id.desc())
    )
    if system_id is not None:
        stmt = stmt.where(DroneTelemetry.system_id == system_id)
    stmt = stmt.limit(limit)

    latest_by_drone: dict[str, dict[str, Any]] = {}
    for row in session.scalars(stmt).all():
        drone_id = str(row.system_id) if row.system_id is not None else "unknown"
        if drone_id in latest_by_drone:
            continue

        payload = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        data = _parse_json(payload.get("data"))
        data = data if isinstance(data, dict) else {}
        battery_remaining = _to_float(data.get("battery_remaining"))
        voltage_battery = _to_float(data.get("voltage_battery"))
        current_battery = _to_float(data.get("current_battery"))
        battery_soc = _to_float(data.get("soc"))
        if (
            battery_remaining is None
            and voltage_battery is None
            and current_battery is None
            and battery_soc is None
        ):
            continue

        latest_by_drone[drone_id] = {
            "battery_remaining": battery_remaining,
            "voltage_battery": voltage_battery,
            "current_battery": current_battery,
            "battery_soc": battery_soc,
            "battery_telemetry_at": _serialize_datetime(row.telemetry_at),
        }

    return latest_by_drone


def _merge_drone_batteries(
    drones: list[dict[str, Any]],
    batteries_by_drone: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            **drone,
            **batteries_by_drone.get(str(drone.get("drone_id")), {}),
        }
        for drone in drones
    ]


def _get_fire_detections(
    *,
    session: Session,
    limit: int,
    confirmation: Literal["all", "pending", "confirmed", "rejected"],
) -> list[dict[str, Any]]:
    stmt = (
        select(FireEvent)
        .where(FireEvent.lat.is_not(None), FireEvent.lon.is_not(None))
        .order_by(FireEvent.received_at.desc(), FireEvent.id.desc())
        .limit(limit)
    )

    if confirmation == "pending":
        stmt = stmt.where(FireEvent.user_confirmation.is_(None))
    elif confirmation == "confirmed":
        stmt = stmt.where(FireEvent.user_confirmation == "Y")
    elif confirmation == "rejected":
        stmt = stmt.where(FireEvent.user_confirmation == "N")

    events = session.scalars(stmt).all()
    return [
        {
            "event_id": event.event_id,
            "status": _fire_status(event),
            "lat": _to_float(event.lat),
            "lon": _to_float(event.lon),
            "alt": _to_float(event.alt),
            "position": [_to_float(event.lat), _to_float(event.lon)],
            "confidence": _to_float(event.confidence),
            "captured_at": _serialize_datetime(event.captured_at),
            "received_at": _serialize_datetime(event.received_at),
            "image_url": _event_image_url(event),
            "user_confirmation": event.user_confirmation,
        }
        for event in events
    ]


@router.get("/map/drone-paths")
def get_map_drone_paths(
    system_id: int | None = Query(None, ge=1),
    message_limit: int = Query(3000, ge=1, le=10000),
    point_limit: int = Query(500, ge=1, le=5000),
    stream_key: str = Query(DEFAULT_DRONE_STREAM_KEY, min_length=1),
):
    """Return drone paths as Leaflet Polyline-ready coordinate arrays."""
    result = _get_drone_paths(
        system_id=system_id,
        message_limit=message_limit,
        point_limit=point_limit,
        stream_key=stream_key,
    )
    return {"ok": result["redis_available"], **result}


@router.get("/map/fire-detections")
def get_map_fire_detections(
    limit: int = Query(100, ge=1, le=1000),
    confirmation: Literal["all", "pending", "confirmed", "rejected"] = Query("all"),
    session: Session = Depends(get_db_session),
):
    """Return fire detection locations as Leaflet Marker-ready coordinate arrays."""
    detections = _get_fire_detections(session=session, limit=limit, confirmation=confirmation)
    return {
        "ok": True,
        "count": len(detections),
        "items": detections,
    }


@router.get("/map/overview")
def get_map_overview(
    system_id: int | None = Query(None, ge=1),
    message_limit: int = Query(3000, ge=1, le=10000),
    point_limit: int = Query(500, ge=1, le=5000),
    fire_limit: int = Query(100, ge=1, le=1000),
    confirmation: Literal["all", "pending", "confirmed", "rejected"] = Query("all"),
    stream_key: str = Query(DEFAULT_DRONE_STREAM_KEY, min_length=1),
    session: Session = Depends(get_db_session),
):
    """Return drone paths and fire markers in one response for the map screen."""
    drone_paths = _get_drone_paths(
        system_id=system_id,
        message_limit=message_limit,
        point_limit=point_limit,
        stream_key=stream_key,
    )
    fire_detections = _get_fire_detections(session=session, limit=fire_limit, confirmation=confirmation)
    batteries_by_drone = _get_latest_battery_by_drone(session=session, system_id=system_id)
    drones = _merge_drone_batteries(drone_paths["drones"], batteries_by_drone)

    return {
        "ok": True,
        "redis_available": drone_paths["redis_available"],
        "stream_key": drone_paths["stream_key"],
        "drone_path_source": drone_paths.get("source"),
        "sampled_message_count": drone_paths.get("sampled_message_count", 0),
        "drone_paths": drones,
        "fire_detections": fire_detections,
    }

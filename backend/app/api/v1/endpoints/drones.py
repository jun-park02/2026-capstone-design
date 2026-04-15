import os
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Query
from pymavlink import mavutil

from app import runtime


router = APIRouter(tags=["drones"])

DRONE_LAST_SEEN_KEY = os.getenv("DRONE_LAST_SEEN_KEY", "drone:last_seen")
DRONE_STATUS_KEY_PREFIX = os.getenv("DRONE_STATUS_KEY_PREFIX", "drone:status")
DEFAULT_ACTIVE_TIMEOUT_SEC = int(os.getenv("DRONE_ACTIVE_TIMEOUT_SEC", "5"))


def _drone_status_key(drone_id: str) -> str:
    return f"{DRONE_STATUS_KEY_PREFIX}:{drone_id}"


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

        if system_status != mavutil.mavlink.MAV_STATE_ACTIVE:
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

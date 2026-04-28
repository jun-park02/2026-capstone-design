import json
import os
import time
from typing import Any

import redis
from pymavlink import mavutil


UDP_PORT = int(os.getenv("UDP_PORT", "14550"))
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
STREAM_KEY = os.getenv("STREAM_KEY", "mystream")
DRONE_LAST_SEEN_KEY = os.getenv("DRONE_LAST_SEEN_KEY", "drone:last_seen")
DRONE_STATUS_KEY_PREFIX = os.getenv("DRONE_STATUS_KEY_PREFIX", "drone:status")
DRONE_STATUS_TTL_SEC = int(os.getenv("DRONE_STATUS_TTL_SEC", "86400"))
MAVLINK_SAMPLE_INTERVAL_SEC = float(os.getenv("MAVLINK_SAMPLE_INTERVAL_SEC", "2"))


def create_redis_client():
    try:
        client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=0,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        client.ping()
        print(f"[RX] Redis 연결 성공: {REDIS_HOST}:{REDIS_PORT}")
        return client
    except Exception as exc:
        print(f"[RX] Redis 연결 실패: {exc}")
        return None


def get_message_source_ids(msg) -> tuple[int | None, int | None]:
    """MAVLink 메시지에서 sysid, compid를 안전하게 추출한다."""
    system_id = None
    component_id = None

    try:
        system_id = msg.get_srcSystem()
    except Exception:
        pass

    try:
        component_id = msg.get_srcComponent()
    except Exception:
        pass

    return system_id, component_id


def get_mav_state_name(system_status: Any) -> str:
    """MAV_STATE enum 값을 사람이 읽기 쉬운 문자열로 바꾼다."""
    try:
        enum_entry = mavutil.mavlink.enums["MAV_STATE"][int(system_status)]
        return enum_entry.name
    except Exception:
        return str(system_status) if system_status is not None else "UNKNOWN"


def should_process_message(
    last_processed_at: dict[tuple[int | str, int | str, str], float],
    *,
    msg_type: str,
    system_id: int | None,
    component_id: int | None,
    now: float,
) -> bool:
    if MAVLINK_SAMPLE_INTERVAL_SEC <= 0:
        return True

    message_key = (
        system_id if system_id is not None else "unknown",
        component_id if component_id is not None else "unknown",
        msg_type,
    )
    last_seen = last_processed_at.get(message_key)
    if last_seen is not None and now - last_seen < MAVLINK_SAMPLE_INTERVAL_SEC:
        return False

    last_processed_at[message_key] = now
    return True


def update_drone_status(
    redis_client,
    *,
    msg_type: str,
    msg_dict: dict[str, Any],
    system_id: int | None,
    component_id: int | None,
):
    """
    HEARTBEAT 메시지를 기준으로 드론별 최신 상태를 Redis에 저장한다.

    Streams는 원본 메시지 이력을 쌓는 용도이고,
    이 별도 키는 "현재 활성 드론 수"처럼 최신 상태 기반 집계를 빠르게 하기 위한 저장소다.
    """
    if not redis_client or msg_type != "HEARTBEAT" or system_id is None:
        return

    now_ts = time.time()
    system_status = msg_dict.get("system_status")
    status_key = f"{DRONE_STATUS_KEY_PREFIX}:{system_id}"

    pipe = redis_client.pipeline()
    pipe.zadd(DRONE_LAST_SEEN_KEY, {str(system_id): now_ts})
    pipe.hset(
        status_key,
        mapping={
            "system_id": system_id,
            "component_id": component_id if component_id is not None else "",
            "message_type": msg_type,
            "system_status": system_status if system_status is not None else "",
            "system_status_name": get_mav_state_name(system_status),
            "base_mode": msg_dict.get("base_mode", ""),
            "custom_mode": msg_dict.get("custom_mode", ""),
            "last_seen_ts": now_ts,
            "last_seen_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )
    pipe.expire(status_key, DRONE_STATUS_TTL_SEC)
    pipe.zremrangebyscore(DRONE_LAST_SEEN_KEY, 0, now_ts - DRONE_STATUS_TTL_SEC)
    pipe.execute()

    print(
        f"[RX] 드론 상태 갱신: sysid={system_id} compid={component_id} "
        f"status={get_mav_state_name(system_status)}"
    )


def main():
    redis_client = create_redis_client()
    print(f"[RX] UDP 수신 시작: 0.0.0.0:{UDP_PORT}")
    print(f"[RX] Redis Stream: {STREAM_KEY}")
    print(f"[RX] MAVLink sample interval: {MAVLINK_SAMPLE_INTERVAL_SEC}s")
    print(f"[RX] 드론 상태 키: {DRONE_LAST_SEEN_KEY}, {DRONE_STATUS_KEY_PREFIX}:<sysid>")

    mav = mavutil.mavlink_connection(f"udp:0.0.0.0:{UDP_PORT}")
    last_processed_at: dict[tuple[int | str, int | str, str], float] = {}

    while True:
        # recv_match는 pymavlink가 제공하는 MAVLink 메시지 수신 함수다.
        msg = mav.recv_match(blocking=True)
        if not msg:
            continue

        msg_type = msg.get_type()
        msg_dict = msg.to_dict()
        system_id, component_id = get_message_source_ids(msg)

        if not should_process_message(
            last_processed_at,
            msg_type=msg_type,
            system_id=system_id,
            component_id=component_id,
            now=time.monotonic(),
        ):
            continue

        print(f"[RX] {msg_type} sysid={system_id} compid={component_id}: {msg_dict}")

        if redis_client:
            try:
                update_drone_status(
                    redis_client,
                    msg_type=msg_type,
                    msg_dict=msg_dict,
                    system_id=system_id,
                    component_id=component_id,
                )

                payload = {
                    "message_type": msg_type,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "system_id": system_id,
                    "component_id": component_id,
                    "data": json.dumps(msg_dict),
                }
                msg_id = redis_client.xadd(
                    STREAM_KEY,
                    {"payload": json.dumps(payload)},
                    maxlen=10000,
                    approximate=True,
                )
                print(f"[RX] Redis Stream 저장: {msg_id}")
            except Exception as exc:
                print(f"[RX] Redis 저장 오류: {exc}")


if __name__ == "__main__":
    main()

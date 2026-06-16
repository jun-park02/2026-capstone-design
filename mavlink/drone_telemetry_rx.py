import json
import os
import socket
import time
from typing import Any

import redis


UDP_HOST = os.getenv("UDP_HOST", "0.0.0.0")
UDP_PORT = int(os.getenv("UDP_PORT", "14550"))
UDP_BUFFER_SIZE = int(os.getenv("UDP_BUFFER_SIZE", "65535"))

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
STREAM_KEY = os.getenv("STREAM_KEY", "drone_telemetry")

DEFAULT_DRONE_ID = int(os.getenv("DEFAULT_DRONE_ID", "1"))
DRONE_LAST_SEEN_KEY = os.getenv("DRONE_LAST_SEEN_KEY", "drone:last_seen")
DRONE_STATUS_KEY_PREFIX = os.getenv("DRONE_STATUS_KEY_PREFIX", "drone:status")
DRONE_STATUS_TTL_SEC = int(os.getenv("DRONE_STATUS_TTL_SEC", "86400"))
JSON_SAMPLE_INTERVAL_SEC = float(os.getenv("JSON_SAMPLE_INTERVAL_SEC", "2"))
SIMTIME_UNIT = os.getenv("SIMTIME_UNIT", "seconds").strip().lower()


MAV_STATE_NAMES = {
    0: "MAV_STATE_UNINIT",
    1: "MAV_STATE_BOOT",
    2: "MAV_STATE_CALIBRATING",
    3: "MAV_STATE_STANDBY",
    4: "MAV_STATE_ACTIVE",
    5: "MAV_STATE_CRITICAL",
    6: "MAV_STATE_EMERGENCY",
    7: "MAV_STATE_POWEROFF",
    8: "MAV_STATE_FLIGHT_TERMINATION",
}

STATUS_CODE_TO_VEHICLE_STATUS = {
    0: "DISARMED",
    1: "ARMED",
    2: "MC_MODE_FLYING",
    3: "FW_MODE_FLYING",
    4: "TRANSITION",
    5: "BACKTRANSITION",
    6: "INVALID_STATE",
}

VEHICLE_STATUS_TO_FLAGS = {
    "DISARMED": {"armed": False, "flight_enable": False},
    "ARMED": {"armed": True, "flight_enable": False},
    "MC_MODE_FLYING": {"armed": True, "flight_enable": True},
    "FW_MODE_FLYING": {"armed": True, "flight_enable": True},
    "TRANSITION": {"armed": True, "flight_enable": True},
    "BACKTRANSITION": {"armed": True, "flight_enable": True},
    "INVALID_STATE": {"armed": False, "flight_enable": False},
    # Backward compatibility for older test senders.
    "MC_STANDBY": {"armed": False, "flight_enable": False},
    "MC_ARMED_STANDBY": {"armed": True, "flight_enable": False},
    "MC_FLYING": {"armed": True, "flight_enable": True},
    "MC_INVALID_STATE": {"armed": False, "flight_enable": False},
}

VEHICLE_STATUS_TO_MAV_STATE = {
    "DISARMED": 3,
    "ARMED": 3,
    "MC_MODE_FLYING": 4,
    "FW_MODE_FLYING": 4,
    "TRANSITION": 4,
    "BACKTRANSITION": 4,
    "INVALID_STATE": 5,
    # Backward compatibility for older test senders.
    "MC_STANDBY": 3,
    "MC_ARMED_STANDBY": 3,
    "MC_FLYING": 4,
    "MC_INVALID_STATE": 5,
}


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
        print(f"[RX] Redis connected: {REDIS_HOST}:{REDIS_PORT}")
        return client
    except Exception as exc:
        print(f"[RX] Redis connection failed: {exc}")
        return None


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def meters_to_millimeters(value: Any) -> int | None:
    number_value = to_float(value)
    if number_value is None:
        return None
    return int(round(number_value * 1000))


def volts_to_millivolts(value: Any) -> int | None:
    number_value = to_float(value)
    if number_value is None:
        return None
    return int(round(number_value * 1000))


def speed_to_centimeters_per_second(value: Any) -> int | None:
    number_value = to_float(value)
    if number_value is None:
        return None
    return int(round(number_value * 100))


def normalize_simtime_to_time_boot_ms(value: Any) -> int | None:
    simtime = to_float(value)
    if simtime is None:
        return None
    if SIMTIME_UNIT in {"millisecond", "milliseconds", "ms"}:
        return int(round(simtime))
    return int(round(simtime * 1000))


def normalize_vehicle_status(value: Any) -> str:
    code = to_int(value)
    if code is not None and code in STATUS_CODE_TO_VEHICLE_STATUS:
        return STATUS_CODE_TO_VEHICLE_STATUS[code]
    return str(value or "UNKNOWN").strip().upper() or "UNKNOWN"


def get_mav_state_name(system_status: Any, vehicle_status: str | None = None) -> str:
    if vehicle_status and vehicle_status != "UNKNOWN":
        return vehicle_status

    try:
        return MAV_STATE_NAMES[int(system_status)]
    except Exception:
        return str(system_status) if system_status is not None else "UNKNOWN"


def get_system_id(packet: dict[str, Any]) -> int:
    drone_id = to_int(packet.get("drone_id"))
    if drone_id is not None:
        return drone_id
    return DEFAULT_DRONE_ID


def first_present(packet: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in packet and packet[key] is not None and packet[key] != "":
            return packet[key]
    return None


def should_process_packet(
    last_processed_at: dict[int | str, float],
    *, # * 뒤의 인자들은 반드시 이름을 붙여서 전달하라는 의미
    system_id: int | None,
    now: float,
) -> bool:
    if JSON_SAMPLE_INTERVAL_SEC <= 0:
        return True

    packet_key = system_id if system_id is not None else "unknown"
    last_seen = last_processed_at.get(packet_key)
    if last_seen is not None and now - last_seen < JSON_SAMPLE_INTERVAL_SEC:
        return False

    last_processed_at[packet_key] = now
    return True


def parse_udp_json(data: bytes) -> dict[str, Any]:
    text = data.decode("utf-8")
    packet = json.loads(text)
    # 수신 데이터가 key-value 형태의 JSON 객체인지 확인
    if not isinstance(packet, dict):
        raise ValueError("UDP payload must be a JSON object")
    return packet


def get_lla(packet: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    lla = packet.get("lla")
    if isinstance(lla, (list, tuple)) and len(lla) >= 3:
        return to_float(lla[0]), to_float(lla[1]), to_float(lla[2])

    return (
        to_float(first_present(packet, "lat", "latitude")),
        to_float(first_present(packet, "lon", "lng", "longitude")),
        to_float(first_present(packet, "alt", "altitude")),
    )


def build_global_position_message(packet: dict[str, Any]) -> dict[str, Any] | None:
    lat, lon, alt = get_lla(packet)
    if lat is None or lon is None:
        return None

    relative_altitude = packet.get("relative_altitude")
    heading = to_float(packet.get("heading"))
    va = to_float(packet.get("va"))

    return {
        "mavpackettype": "GLOBAL_POSITION_INT",
        "source_format": "json_udp",
        "simtime": packet.get("simtime"),
        "time_boot_ms": normalize_simtime_to_time_boot_ms(packet.get("simtime")),
        "lat": lat,
        "lon": lon,
        "alt": meters_to_millimeters(alt),
        "relative_alt": meters_to_millimeters(relative_altitude),
        "relative_altitude": to_float(relative_altitude),
        "vx": speed_to_centimeters_per_second(va),
        "vy": 0,
        "vz": 0,
        "hdg": heading,
        "heading": heading,
        "va": va,
    }


def build_vfr_hud_message(packet: dict[str, Any]) -> dict[str, Any] | None:
    va = to_float(packet.get("va"))
    heading = to_float(packet.get("heading"))
    alt = get_lla(packet)[2]
    if va is None and heading is None and alt is None:
        return None

    return {
        "mavpackettype": "VFR_HUD",
        "source_format": "json_udp",
        "simtime": packet.get("simtime"),
        "time_boot_ms": normalize_simtime_to_time_boot_ms(packet.get("simtime")),
        "airspeed": va,
        "groundspeed": va,
        "heading": heading,
        "alt": alt,
        "climb": 0,
        "va": va,
    }


def build_battery_status_message(packet: dict[str, Any]) -> dict[str, Any] | None:
    battery = packet.get("battery")
    if not isinstance(battery, dict):
        return None

    soc = to_float(battery.get("soc"))
    voltage = to_float(battery.get("voltage"))
    battery_percent = round(soc * 100, 2) if soc is not None else None

    return {
        "mavpackettype": "BATTERY_STATUS",
        "source_format": "json_udp",
        "simtime": packet.get("simtime"),
        "time_boot_ms": normalize_simtime_to_time_boot_ms(packet.get("simtime")),
        "battery_remaining": battery_percent,
        "voltage_battery": voltage,
        "voltage_battery_mv": volts_to_millivolts(voltage),
        "current_battery": battery.get("current"),
        "soc": soc,
    }


def build_heartbeat_message(packet: dict[str, Any]) -> dict[str, Any] | None:
    raw_status = (
        packet.get("vehicle_status")
        or packet.get("vehicle_Status")
        or packet.get("vehicleStatus")
    )
    if raw_status is None:
        return None

    vehicle_status = normalize_vehicle_status(raw_status)
    flags = VEHICLE_STATUS_TO_FLAGS.get(vehicle_status, {})
    system_status = VEHICLE_STATUS_TO_MAV_STATE.get(vehicle_status)

    return {
        "mavpackettype": "HEARTBEAT",
        "source_format": "json_udp",
        "simtime": packet.get("simtime"),
        "time_boot_ms": normalize_simtime_to_time_boot_ms(packet.get("simtime")),
        "vehicle_status": vehicle_status,
        "armed": flags.get("armed"),
        "flight_enable": flags.get("flight_enable"),
        "system_status": system_status,
        "system_status_name": get_mav_state_name(system_status, vehicle_status),
        "base_mode": "",
        "custom_mode": vehicle_status,
    }


def build_stream_messages(packet: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    # 드론 JSON 1개에서 위치, 속도, 배터리, 상태 정보를 각각 Redis Stream 메시지로 만듦

    # build_global_position_message() -> 위치 메시지 dict: lat, lon, alt, relative_alt, heading, time_boot_ms
    # build_vfr_hud_message() -> 속도/고도 메시지 dict: airspeed, groundspeed, heading, alt
    # build_battery_status_message() -> 배터리 메시지 dict: battery_remaining, voltage_battery, soc
    # build_heartbeat_message() -> 상태 메시지 dict: vehicle_status, armed, flight_enable, system_status
    candidates = [
        ("GLOBAL_POSITION_INT", build_global_position_message(packet)),
        ("VFR_HUD", build_vfr_hud_message(packet)),
        ("BATTERY_STATUS", build_battery_status_message(packet)),
        ("HEARTBEAT", build_heartbeat_message(packet)),
    ]
    # 필요한 값이 없어 만들 수 없는 메시지는 None이므로 제외한다.
    return [(message_type, data) for message_type, data in candidates if data is not None]


def update_drone_status(
    redis_client,
    *,
    msg_type: str,
    msg_dict: dict[str, Any],
    system_id: int | None,
):
    if not redis_client or msg_type != "HEARTBEAT" or system_id is None:
        return

    now_ts = time.time()
    system_status = msg_dict.get("system_status")
    vehicle_status = normalize_vehicle_status(msg_dict.get("vehicle_status"))
    status_key = f"{DRONE_STATUS_KEY_PREFIX}:{system_id}"

    pipe = redis_client.pipeline()
    pipe.zadd(DRONE_LAST_SEEN_KEY, {str(system_id): now_ts})
    pipe.hset(
        status_key,
        mapping={
            "system_id": system_id,
            "message_type": msg_type,
            "vehicle_status": vehicle_status,
            "armed": "" if msg_dict.get("armed") is None else int(bool(msg_dict.get("armed"))),
            "flight_enable": ""
            if msg_dict.get("flight_enable") is None
            else int(bool(msg_dict.get("flight_enable"))),
            "system_status": system_status if system_status is not None else "",
            "system_status_name": get_mav_state_name(system_status, vehicle_status),
            "base_mode": msg_dict.get("base_mode", ""),
            "custom_mode": msg_dict.get("custom_mode", ""),
            "last_seen_ts": now_ts,
            "last_seen_at": now_str(),
        },
    )
    pipe.expire(status_key, DRONE_STATUS_TTL_SEC)
    pipe.zremrangebyscore(DRONE_LAST_SEEN_KEY, 0, now_ts - DRONE_STATUS_TTL_SEC)
    pipe.execute()

    print(
        f"[RX] Drone status updated: drone_id={system_id} status={vehicle_status}"
    )


def publish_message(
    redis_client,
    *,
    message_type: str,
    msg_dict: dict[str, Any],
    system_id: int,
    src_ip: str,
    src_port: int,
) -> str:
    payload = {
        "message_type": message_type,
        "timestamp": now_str(),
        "system_id": system_id,
        "src_ip": src_ip,
        "src_port": src_port,
        "data": json.dumps(msg_dict, ensure_ascii=False),
    }
    msg_id = redis_client.xadd(
        STREAM_KEY,
        {"payload": json.dumps(payload, ensure_ascii=False)},
        maxlen=10000,
        approximate=True,
    )
    return str(msg_id)


def main():
    # Redis 연결을 먼저 시도
    redis_client = create_redis_client()

    print(f"[drone-telemetry-udp-rx] UDP JSON receiver listening: {UDP_HOST}:{UDP_PORT}")
    print(f"[drone-telemetry-udp-rx] Redis Stream: {STREAM_KEY}")
    print(f"[drone-telemetry-udp-rx] JSON sample interval: {JSON_SAMPLE_INTERVAL_SEC}s")
    print(f"[drone-telemetry-udp-rx] Redis drone status keys: {DRONE_LAST_SEEN_KEY}, {DRONE_STATUS_KEY_PREFIX}:<drone_id>")

    # 예{1: 12345.12, 2: 12348.75} 형태로 드론별 마지막 처리 시간을 저장
    # 마지막 처리 시간은 time.monotonic() 함수로 구함
    last_processed_at: dict[int | str, float] = {}

    # 표준 socket 라이브러리로 UDP 소켓을 열고 지정된 포트에 바인딩
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_HOST, UDP_PORT))

    while True:
        # recvfrom은 UDP 패킷 1개와 송신자 주소를 함께 반환
        # UDP_BUFFER_SIZE : 최대 몇 바이트까지 읽을지 정함
        data, address = sock.recvfrom(UDP_BUFFER_SIZE)
        src_ip, src_port = address

        try:
            # 드론에서 보낸 바이트 데이터를 UTF-8 JSON 객체로 변환
            packet = parse_udp_json(data)
        except Exception as e:
            print(f"[drone-telemetry-udp-rx] Invalid JSON from {src_ip}:{src_port}: {e}")
            continue

        # JSON의 drone_id 값을 기존 백엔드 payload의 system_id로 사용
        system_id = get_system_id(packet)

        # 같은 드론에서 너무 빠르게 들어오는 패킷은 샘플링 간격에 따라 건너뜀
        if not should_process_packet(
            last_processed_at,
            system_id=system_id,
            now=time.monotonic(),
        ):
            continue

        # 수신한 JSON 1개를 위치, 속도, 배터리, 상태 메시지로 나누어 Redis에 저장
        messages = build_stream_messages(packet)
        if not messages:
            print(f"[drone-telemetry-udp-rx] No usable telemetry fields from {src_ip}:{src_port}: {packet}")
            continue

        print(
            f"[drone-telemetry-udp-rx] JSON drone_id={system_id} src={src_ip}:{src_port}: {packet}"
        )

        if not redis_client:
            redis_client = create_redis_client()
            continue

        for message_type, msg_dict in messages:
            try:
                # HEARTBEAT 메시지일 때는 최신 드론 상태 캐시도 함께 갱신한다.
                update_drone_status(
                    redis_client,
                    msg_type=message_type,
                    msg_dict=msg_dict,
                    system_id=system_id,
                )

                # 기존 백엔드 소비자가 읽는 Redis Stream payload 형식으로 발행한다.
                msg_id = publish_message(
                    redis_client,
                    message_type=message_type,
                    msg_dict=msg_dict,
                    system_id=system_id,
                    src_ip=src_ip,
                    src_port=src_port,
                )
                print(f"[drone-telemetry-udp-rx] Redis Stream saved: {msg_id} type={message_type}")
            except Exception as exc:
                print(f"[drone-telemetry-udp-rx] Redis save failed: {exc}")


if __name__ == "__main__":
    main()

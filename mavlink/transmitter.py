import json
import math
import os
import socket
import time


SYSTEM_ID = int(os.getenv("SYSTEM_ID", "1"))
COMPONENT_ID = int(os.getenv("COMPONENT_ID", "1"))
POSITION_OFFSET = float(os.getenv("POSITION_OFFSET", "0"))
ALT_OFFSET = float(os.getenv("ALT_OFFSET", "0"))
MOVEMENT_MODE = os.getenv("MOVEMENT_MODE", "linear").lower()
LINEAR_STEP = float(os.getenv("LINEAR_STEP", "0.0001"))
ALT_STEP = float(os.getenv("ALT_STEP", "0.5"))
CIRCLE_RADIUS_METERS = float(os.getenv("CIRCLE_RADIUS_METERS", "250"))
CIRCLE_PERIOD_STEPS = max(1, int(os.getenv("CIRCLE_PERIOD_STEPS", "120")))
CIRCLE_START_DEGREES = float(os.getenv("CIRCLE_START_DEGREES", "0"))

TARGET_IP = os.getenv("TARGET_IP", "udp-rx")
TARGET_PORT = int(os.getenv("TARGET_PORT", "14550"))
SEND_INTERVAL_SEC = float(os.getenv("SEND_INTERVAL_SEC", "0.2"))

BASE_LAT = float(os.getenv("BASE_LAT", "37.5665"))
BASE_LON = float(os.getenv("BASE_LON", "126.9780"))
BASE_ALT = float(os.getenv("BASE_ALT", "50.0"))
BASE_HEADING = float(os.getenv("BASE_HEADING", "166.97"))
BASE_VA = float(os.getenv("BASE_VA", "0.0"))
BATTERY_SOC = float(os.getenv("BATTERY_SOC", "0.9781"))
BATTERY_VOLTAGE = float(os.getenv("BATTERY_VOLTAGE", "49.48"))
VEHICLE_STATUS = os.getenv("VEHICLE_STATUS", "MC_FLYING")
METERS_PER_DEGREE_LAT = 111_320


def meters_to_lon_degrees(meters: float, latitude: float) -> float:
    scale = METERS_PER_DEGREE_LAT * math.cos(math.radians(latitude))
    if abs(scale) < 1e-9:
        return 0
    return meters / scale


def get_position(seq: int) -> tuple[float, float, float]:
    center_lat = BASE_LAT + POSITION_OFFSET
    center_lon = BASE_LON + POSITION_OFFSET

    if MOVEMENT_MODE == "circle":
        angle = math.radians(CIRCLE_START_DEGREES) + (
            2 * math.pi * (seq % CIRCLE_PERIOD_STEPS) / CIRCLE_PERIOD_STEPS
        )
        lat = center_lat + (math.cos(angle) * CIRCLE_RADIUS_METERS / METERS_PER_DEGREE_LAT)
        lon = center_lon + (math.sin(angle) * meters_to_lon_degrees(CIRCLE_RADIUS_METERS, center_lat))
        alt = BASE_ALT + ALT_OFFSET
        return lat, lon, alt

    lat = center_lat + (seq * LINEAR_STEP)
    lon = center_lon + (seq * LINEAR_STEP)
    alt = BASE_ALT + ALT_OFFSET + (seq * ALT_STEP)
    return lat, lon, alt


def build_payload(seq: int, started_at: float) -> dict:
    lat, lon, alt = get_position(seq)
    return {
        "system_id": SYSTEM_ID,
        "component_id": COMPONENT_ID,
        "simtime": round(time.monotonic() - started_at, 3),
        "lla": [round(lat, 8), round(lon, 8), round(alt, 2)],
        "relative_altitude": round(alt - BASE_ALT, 2),
        "va": BASE_VA,
        "heading": BASE_HEADING,
        "battery": {
            "soc": BATTERY_SOC,
            "voltage": BATTERY_VOLTAGE,
        },
        "vehicle_status": VEHICLE_STATUS,
    }


def main():
    seq = 0
    started_at = time.monotonic()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(
        f"[TX] JSON UDP sysid={SYSTEM_ID}, compid={COMPONENT_ID}, "
        f"target={TARGET_IP}:{TARGET_PORT}, position_offset={POSITION_OFFSET}, "
        f"alt_offset={ALT_OFFSET}, movement_mode={MOVEMENT_MODE}"
    )

    while True:
        payload = build_payload(seq, started_at)
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        sock.sendto(encoded, (TARGET_IP, TARGET_PORT))

        lat, lon, alt = payload["lla"]
        print(
            f"[TX] seq={seq}, target={TARGET_IP}:{TARGET_PORT}, "
            f"lat={lat:.6f}, lon={lon:.6f}, alt={alt:.1f}m, "
            f"status={payload['vehicle_status']}"
        )
        seq += 1
        time.sleep(SEND_INTERVAL_SEC)


if __name__ == "__main__":
    main()

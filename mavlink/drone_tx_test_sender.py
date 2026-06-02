import json
import math
import os
import socket
import time


CONTAINER_NAME = os.getenv("CONTAINER_NAME", "TX").upper()

# 전송할 테스트 드론의 ID
DRONE_ID = int(os.getenv("DRONE_ID", "1"))
# 여러 테스트 드론의 시작 위치가 겹치지 않도록 위도/경도에 더하는 값
POSITION_OFFSET = float(os.getenv("POSITION_OFFSET", "0"))
# 기준 고도에서 추가로 띄울 높이
ALT_OFFSET = float(os.getenv("ALT_OFFSET", "0"))
# 위치 이동 방식: linear는 직선 이동, circle은 원형 이동
MOVEMENT_MODE = os.getenv("MOVEMENT_MODE", "linear").lower()
# linear 모드에서 패킷을 보낼 때마다 위도/경도에 더하는 값
LINEAR_STEP = float(os.getenv("LINEAR_STEP", "0.0001"))
# linear 모드에서 패킷을 보낼 때마다 고도에 더하는 값(고도 증가량)
ALT_STEP = float(os.getenv("ALT_STEP", "0.5"))
# circle 모드에서 원형 경로의 반지름
CIRCLE_RADIUS_METERS = float(os.getenv("CIRCLE_RADIUS_METERS", "250"))
# circle 모드에서 한 바퀴를 도는 데 필요한 전송 횟수
CIRCLE_PERIOD_STEPS = max(1, int(os.getenv("CIRCLE_PERIOD_STEPS", "120")))
# circle 모드에서 원형 이동을 시작할 각도
CIRCLE_START_DEGREES = float(os.getenv("CIRCLE_START_DEGREES", "0"))
# rectangle mode route size and loop duration
RECTANGLE_WIDTH_METERS = max(1.0, float(os.getenv("RECTANGLE_WIDTH_METERS", "500")))
RECTANGLE_HEIGHT_METERS = max(1.0, float(os.getenv("RECTANGLE_HEIGHT_METERS", "300")))
RECTANGLE_PERIOD_STEPS = max(4, int(os.getenv("RECTANGLE_PERIOD_STEPS", "160")))

# UDP JSON을 받을 수신 서버 주소
TARGET_IP = os.getenv("TARGET_IP", "udp-rx")
# UDP JSON을 받을 수신 서버 포트
TARGET_PORT = int(os.getenv("TARGET_PORT", "14550"))
# UDP 패킷 전송 간격
SEND_INTERVAL_SEC = float(os.getenv("SEND_INTERVAL_SEC", "0.2"))

# 테스트 드론 위치 계산에 사용할 기준 위도
BASE_LAT = float(os.getenv("BASE_LAT", "37.5665"))
# 테스트 드론 위치 계산에 사용할 기준 경도
BASE_LON = float(os.getenv("BASE_LON", "126.9780"))
# 테스트 드론 위치 계산에 사용할 기준 고도
BASE_ALT = float(os.getenv("BASE_ALT", "50.0"))
# 전송 payload에 넣을 heading 값
BASE_HEADING = float(os.getenv("BASE_HEADING", "166.97"))
# 전송 payload에 넣을 상대속도 va 값
BASE_VA = float(os.getenv("BASE_VA", "0.0"))
# 전송 payload에 넣을 배터리 잔량 비율
BATTERY_SOC = float(os.getenv("BATTERY_SOC", "0.9781"))
# 전송 payload에 넣을 배터리 전압
BATTERY_VOLTAGE = float(os.getenv("BATTERY_VOLTAGE", "49.48"))
# 전송 payload에 넣을 드론 상태 값
VEHICLE_STATUS = os.getenv("VEHICLE_STATUS", "MC_FLYING")
# 위도 1도를 미터로 환산할 때 사용하는 근사값
METERS_PER_DEGREE_LAT = 111_320


def meters_to_lon_degrees(meters: float, latitude: float) -> float:
    scale = METERS_PER_DEGREE_LAT * math.cos(math.radians(latitude))
    if abs(scale) < 1e-9:
        return 0
    return meters / scale


def offset_position(
    center_lat: float,
    center_lon: float,
    *,
    north_meters: float,
    east_meters: float,
) -> tuple[float, float]:
    lat = center_lat + (north_meters / METERS_PER_DEGREE_LAT)
    lon = center_lon + meters_to_lon_degrees(east_meters, center_lat)
    return lat, lon


def get_position(seq: int) -> tuple[float, float, float, float]:
    center_lat = BASE_LAT + POSITION_OFFSET
    center_lon = BASE_LON + POSITION_OFFSET

    if MOVEMENT_MODE == "circle":
        angle = math.radians(CIRCLE_START_DEGREES) + (
            2 * math.pi * (seq % CIRCLE_PERIOD_STEPS) / CIRCLE_PERIOD_STEPS
        )
        lat = center_lat + (math.cos(angle) * CIRCLE_RADIUS_METERS / METERS_PER_DEGREE_LAT)
        lon = center_lon + (math.sin(angle) * meters_to_lon_degrees(CIRCLE_RADIUS_METERS, center_lat))
        alt = BASE_ALT + ALT_OFFSET
        heading = (math.degrees(angle) + 90) % 360
        return lat, lon, alt, heading

    if MOVEMENT_MODE == "rectangle":
        width = RECTANGLE_WIDTH_METERS
        height = RECTANGLE_HEIGHT_METERS
        half_width = width / 2
        half_height = height / 2
        perimeter = (width + height) * 2
        distance = (seq % RECTANGLE_PERIOD_STEPS) / RECTANGLE_PERIOD_STEPS * perimeter

        if distance < width:
            east_meters = -half_width + distance
            north_meters = half_height
            heading = 90
        elif distance < width + height:
            east_meters = half_width
            north_meters = half_height - (distance - width)
            heading = 180
        elif distance < (2 * width) + height:
            east_meters = half_width - (distance - width - height)
            north_meters = -half_height
            heading = 270
        else:
            east_meters = -half_width
            north_meters = -half_height + (distance - (2 * width) - height)
            heading = 0

        lat, lon = offset_position(
            center_lat,
            center_lon,
            north_meters=north_meters,
            east_meters=east_meters,
        )
        alt = BASE_ALT + ALT_OFFSET
        return lat, lon, alt, heading

    lat = center_lat + (seq * LINEAR_STEP)
    lon = center_lon + (seq * LINEAR_STEP)
    alt = BASE_ALT + ALT_OFFSET + (seq * ALT_STEP)
    return lat, lon, alt, BASE_HEADING


def build_payload(seq: int, started_at: float) -> dict:
    lat, lon, alt, heading = get_position(seq)
    return {
        "drone_id": DRONE_ID,
        "simtime": round(time.monotonic() - started_at, 3),
        "lla": [round(lat, 8), round(lon, 8), round(alt, 2)],
        "relative_altitude": round(alt - BASE_ALT, 2),
        "va": BASE_VA,
        "heading": round(heading, 2),
        "battery": {
            "soc": BATTERY_SOC,
            "voltage": BATTERY_VOLTAGE,
        },
        "vehicle_status": VEHICLE_STATUS,
    }


def main():
    # seq는 보낸 패킷 순번이며, 위치 변화 계산에도 사용
    seq = 0
    # simtime 계산을 위해 송신기가 시작된 시간을 저장
    started_at = time.monotonic()
    # UDP 방식으로 JSON payload를 보내기 위한 소켓 생성
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(
        f"[{CONTAINER_NAME}] JSON UDP drone_id={DRONE_ID}, target={TARGET_IP}:{TARGET_PORT}, "
        f"position_offset={POSITION_OFFSET}, "
        f"alt_offset={ALT_OFFSET}, movement_mode={MOVEMENT_MODE}"
    )

    while True:
        # 현재 순번 기준으로 드론 테스트 telemetry payload 생성
        payload = build_payload(seq, started_at)
        # JSON 문자열을 UTF-8 바이트로 변환해서 UDP로 전송
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        sock.sendto(encoded, (TARGET_IP, TARGET_PORT))

        # 터미널에서 송신 중인 위치와 상태를 확인하기 위한 로그 출력
        lat, lon, alt = payload["lla"]
        print(
            f"[{CONTAINER_NAME}] seq={seq}, target={TARGET_IP}:{TARGET_PORT}, "
            f"lat={lat:.6f}, lon={lon:.6f}, alt={alt:.1f}m, "
            f"heading={payload['heading']:.1f}, "
            f"status={payload['vehicle_status']}"
        )
        # 다음 패킷에서 위치가 변하도록 순번 증가
        seq += 1
        # 설정된 간격만큼 기다린 뒤 다음 UDP 패킷 전송
        time.sleep(SEND_INTERVAL_SEC)


if __name__ == "__main__":
    main()

from pymavlink.dialects.v20 import common as mavlink2
import os
import socket
import time

# MAVLink 인코더(발신자) 생성
mav = mavlink2.MAVLink(None)

MAVLINK_SYS_ID = int(os.getenv("MAVLINK_SYS_ID", "1"))
MAVLINK_COMP_ID = int(os.getenv("MAVLINK_COMP_ID", "1"))
POSITION_OFFSET = float(os.getenv("POSITION_OFFSET", "0"))
ALT_OFFSET = float(os.getenv("ALT_OFFSET", "0"))

mav.srcSystem = MAVLINK_SYS_ID
mav.srcComponent = MAVLINK_COMP_ID

# 환경 변수에서 대상 IP/포트를 가져오기
TARGET_IP = os.getenv("TARGET_IP", "udp-rx")
TARGET_PORT = int(os.getenv("TARGET_PORT", "14550"))


def send_udp(payload: bytes, ip=None, port=None):
    if ip is None:
        ip = TARGET_IP
    if port is None:
        port = TARGET_PORT

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(payload, (ip, port))
    sock.close()


def main():
    seq = 0
    print(
        f"[TX] sysid={MAVLINK_SYS_ID}, compid={MAVLINK_COMP_ID}, "
        f"target={TARGET_IP}:{TARGET_PORT}, position_offset={POSITION_OFFSET}, alt_offset={ALT_OFFSET}"
    )

    while True:
        hb = mav.heartbeat_encode(
            type=mavlink2.MAV_TYPE_QUADROTOR,
            autopilot=mavlink2.MAV_AUTOPILOT_ARDUPILOTMEGA,
            base_mode=0,
            custom_mode=0,
            system_status=mavlink2.MAV_STATE_ACTIVE,
        )
        send_udp(hb.pack(mav))

        att = mav.attitude_encode(
            time_boot_ms=int(time.time() * 1000) & 0xFFFFFFFF,
            roll=0.1,
            pitch=0.05,
            yaw=1.2,
            rollspeed=0.0,
            pitchspeed=0.0,
            yawspeed=0.0,
        )
        send_udp(att.pack(mav))

        # 위치 정보는 드론별 오프셋과 seq 기반으로 조금씩 변화시킨다.
        lat = 37.5665 + POSITION_OFFSET + (seq * 0.0001)
        lon = 126.9780 + POSITION_OFFSET + (seq * 0.0001)
        alt = 50.0 + ALT_OFFSET + (seq * 0.5)

        global_pos = mav.global_position_int_encode(
            time_boot_ms=int(time.time() * 1000) & 0xFFFFFFFF,
            lat=int(lat * 1e7),
            lon=int(lon * 1e7),
            alt=int(alt * 1000),
            relative_alt=int(alt * 1000),
            vx=0,
            vy=0,
            vz=0,
            hdg=0,
        )
        send_udp(global_pos.pack(mav))

        print(
            f"[TX] sysid={MAVLINK_SYS_ID}, seq={seq}, target={TARGET_IP}:{TARGET_PORT}, "
            f"lat={lat:.6f}, lon={lon:.6f}, alt={alt:.1f}m"
        )
        seq += 1
        time.sleep(0.2)


if __name__ == "__main__":
    main()

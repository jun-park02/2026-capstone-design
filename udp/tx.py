from pymavlink.dialects.v20 import common as mavlink2
import time, socket

# mavlink 인코더(발신자) 생성
# MAVLink는 MAVLink 메시지를 만들어서 바이트로 직렬화해주는 객체
mav = mavlink2.MAVLink(None)
# MAVLink에는 sysid(system id)라는게 있음
# 여러 시스템(드론 A, 드론 B, GCS 등)이 한 네트워크에 있을 수 있기 때문에 누가 보냈는 지를 숫자로 구분함
mav.srcSystem = 1
# sysid가 드론이면 compid느 그 안의 컴포넌트(부품/모듈) 구분
# 오토파일럿, 카메라, 짐벌 등
mav.srcComponent = 1

def send_udp(payload: bytes, ip="127.0.0.1", port=14550):
    # socket.AF_INET, socket.SOCK_DGRAM은 소켓을 만들 때 어떤 주소 체계로, 어떤 통신 방식으로 쓸지 지정하는 옵션
    # AF_INET은 ipv4 체계
    # SOCK_DGRAM은 데이터그램 방식(udp)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(payload, (ip, port))
    sock.close()

seq = 0

while True:
    hb = mav.heartbeat_encode( 
        type=mavlink2.MAV_TYPE_QUADROTOR, # 기체 타입을 나타내는 필드
        autopilot=mavlink2.MAV_AUTOPILOT_ARDUPILOTMEGA, # 오토파일럿 종류를 나타내는 필드
        base_mode=0, # 기본 모드 비트 플래그. ARM 됐는지, 수동입력 활성인지 같은 상태를 비트로 담음
        custom_mode=0, # 커스텀 모드를 담는 필드
        system_status=mavlink2.MAV_STATE_ACTIVE # 시스템 상태를 나타내는 값. ACTIVE는 정상적으로 동작 중 정도의 의미
    )

    pkt = hb.pack(mav)
    send_udp(pkt)

    att = mav.attitude_encode(
        time_boot_ms=int(time.time() * 1000) & 0xFFFFFFFF,
        roll=0.1,
        pitch=0.05,
        yaw=1.2,
        rollspeed=0.0,
        pitchspeed=0.0,
        yawspeed=0.0
    )

    pkt = att.pack(mav)
    send_udp(pkt)

    print(seq)
    seq += 1
    time.sleep(0.2)
    break
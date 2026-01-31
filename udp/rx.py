from pymavlink import mavutil

mav = mavutil.mavlink_connection("udp:0.0.0.0:14550")

while True:
    # recv_match는 pymavlink가 제공하는 mavlink 메시지 수신함수
    # 연결(UDP, Serial, TCP)로 들어오는 바이트들을 읽어서, 조건(type 등)에 맞는 완성된 mavlink 메시지 1개를 찾아 반환하는 함수
    msg = mav.recv_match(blocking=True)

    if not msg:
        continue

    print(msg.get_type(), msg.to_dict())
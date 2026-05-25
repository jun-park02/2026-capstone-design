from pymavlink import mavutil
import os
import redis
import json
import time

# 환경 변수에서 설정 가져오기
UDP_PORT = int(os.getenv("UDP_PORT", "14550"))
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
STREAM_KEY = os.getenv("STREAM_KEY", "mystream")

# Redis 연결
try:
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=0,
        decode_responses=True,
        socket_connect_timeout=5
    )
    r.ping()
    print(f"[RX] Redis 연결 성공: {REDIS_HOST}:{REDIS_PORT}")
except Exception as e:
    print(f"[RX] Redis 연결 실패: {e}")
    r = None

print(f"[RX] UDP 수신 시작: 0.0.0.0:{UDP_PORT}")
print(f"[RX] Redis Stream: {STREAM_KEY}")
mav = mavutil.mavlink_connection(f"udp:0.0.0.0:{UDP_PORT}")

while True:
    # recv_match는 pymavlink가 제공하는 mavlink 메시지 수신함수
    # 연결(UDP, Serial, TCP)로 들어오는 바이트들을 읽어서, 조건(type 등)에 맞는 완성된 mavlink 메시지 1개를 찾아 반환하는 함수
    msg = mav.recv_match(blocking=True)

    if not msg:
        continue

    msg_type = msg.get_type()
    msg_dict = msg.to_dict()
    
    print(f"[RX] {msg_type}: {msg_dict}")

    # Redis Streams에 저장
    if r:
        try:
            data = {
                "message_type": msg_type,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "data": json.dumps(msg_dict)
            }
            # consumer에서 payload 필드로 접근하므로 payload로 감싸서 저장
            msg_id = r.xadd(
                STREAM_KEY,
                {"payload": json.dumps(data)},
                maxlen=10000,
                approximate=True
            )
            print(f"[RX] Redis Stream 저장: {msg_id}")
        except Exception as e:
            print(f"[RX] Redis 저장 오류: {e}")
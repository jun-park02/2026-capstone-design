import json
import os
import time

import redis
from pymavlink import mavutil


UDP_PORT = int(os.getenv("UDP_PORT", "14550"))
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
STREAM_KEY = os.getenv("STREAM_KEY", "mystream")


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


def main():
    redis_client = create_redis_client()
    print(f"[RX] UDP 수신 시작: 0.0.0.0:{UDP_PORT}")
    print(f"[RX] Redis Stream: {STREAM_KEY}")

    mav = mavutil.mavlink_connection(f"udp:0.0.0.0:{UDP_PORT}")

    while True:
        # recv_match는 pymavlink가 제공하는 mavlink 메시지 수신 함수
        msg = mav.recv_match(blocking=True)
        if not msg:
            continue

        msg_type = msg.get_type()
        msg_dict = msg.to_dict()
        print(f"[RX] {msg_type}: {msg_dict}")

        if redis_client:
            try:
                payload = {
                    "message_type": msg_type,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
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
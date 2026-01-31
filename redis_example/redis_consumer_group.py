import redis
import time
import json

r = redis.Redis(decode_responses=True)

STREAM_KEY = "mystream"
GROUP = "mygroup"
CONSUMER = "consumer-1"

print("Start consumer", CONSUMER)

while True:
    resp = r.xreadgroup(
        groupname=GROUP,
        consumername=CONSUMER,
        streams={STREAM_KEY: ">"}, # 그룹에서 아직 전달 안 된 새 메시지
        count=10, # 최대 10개 메시지까지 한 번의 read 호출에서 가져옴
        block=5000 # 새 메시지가 없으면 최대 5초까지 대기. block=0은 무한 대기
    )

    if not resp:
        continue

    for stream_name, messages in resp:
        for msg_id, fields in messages:
            try:
                payload = fields.get("payload")
                data = json.loads(payload)
                print(data)
                print(type(data))

                # 처리 성공 -> ACK
                r.xack(STREAM_KEY, GROUP, msg_id)
                print("ACK:", msg_id)
            except Exception as e:
                print(e)
    
    time.sleep(0.01)

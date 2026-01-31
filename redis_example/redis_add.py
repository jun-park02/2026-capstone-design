import redis
import json
import time

r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

stream_key = "mystream"

for i in range(1, 6):
    payload = {
        "id": i,
        "time": time.strftime("%Y-%m-%d-%H:%M:%S")
    }
    msg_id = r.xadd(stream_key, {"payload": json.dumps(payload)}, maxlen=10000, approximate=True)
    print(msg_id)

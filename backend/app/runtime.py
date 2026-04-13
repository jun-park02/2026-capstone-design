import os

import redis

from app.fire_detect_listener import FireDetectListener
from app.redis_consumer import RedisStreamConsumer


# FastAPI 앱 전역에서 공유하는 런타임 상태를 보관한다.
redis_client: redis.Redis | None = None
consumer: RedisStreamConsumer | None = None
fire_listener: FireDetectListener | None = None
RAW_IMAGE_DIR = os.getenv("RAW_IMAGE_DIR", "/app/images")

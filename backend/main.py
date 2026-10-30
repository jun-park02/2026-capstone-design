import os
from contextlib import asynccontextmanager
import redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app import runtime
from app.api.v1.routers import router as api_v1_router
from app.fire_detect_listener import FireDetectListener
from app.redis_consumer import RedisStreamConsumer


origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173"
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI의 생명주기동안 필요한 백그라운드 리소스를 초기화하고 정리하는 함수

    서버 시작 시 Redis 스트림 컨슈머와 화재 감지 리스너를 시작
    서버 종료 시 관련 리소스를 순서대로 종료
    """
    # 환경 변수 로드 및 Nnoe 검증
    envs = {
        "redis_host": os.getenv("REDIS_HOST"),
        "redis_port": os.getenv("REDIS_PORT"),
        "drone_stream_key": os.getenv("DRONE_STREAM_KEY"),
        "fire_stream_key": os.getenv("FIRE_STREAM_KEY"),
        "group": os.getenv("CONSUMER_GROUP"),
        "block_ms": os.getenv("FIRE_DETECT_BLOCK_MS"),
    }

    for key, value in envs.items():
        if value is None:
            raise RuntimeError(f"Required environment variable is None: {key}")

    
    # 백그라운드 컨슈머(drone redis stream) 시작
    runtime.consumer = RedisStreamConsumer(
        redis_host=envs["redis_host"],
        redis_port=int(envs["redis_port"]),
        stream_key=envs["drone_stream_key"],
        group=envs["group"],
        consumer=None,
    )
    await runtime.consumer.start()

    # redis 클라이언트(앱 전역에서 사용) 초기화
    runtime.redis_client = redis.Redis(
        host=envs["redis_host"],
        port=int(envs["redis_port"]),
        db=0,
        decode_responses=True,
    )

    # fire redis stream 리스너를 생성 및 시작
    runtime.fire_listener = FireDetectListener(
        redis_client=runtime.redis_client,
        raw_image_dir=runtime.RAW_IMAGE_DIR,
        stream_key=envs["fire_stream_key"],
        block_ms=int(envs["block_ms"]),
    )
    await runtime.fire_listener.start()

    yield

    # 서버 종료 시 시작했던 리소스 정리
    if runtime.fire_listener:
        await runtime.fire_listener.stop()
    if runtime.consumer:
        await runtime.consumer.stop()
    if runtime.redis_client:
        runtime.redis_client.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router)

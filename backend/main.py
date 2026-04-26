import os
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import runtime
from app.api.v1.routers import router as api_v1_router
from app.fire_detect_listener import FireDetectListener
from app.redis_consumer import RedisStreamConsumer


def get_cors_origins() -> list[str]:
    origins = os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    return [origin.strip() for origin in origins.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 애플리케이션의 생명주기 동안 필요한 백그라운드 리소스를 초기화하고 정리하는 함수.

    서버 시작 시 Redis 스트림 컨슈머와 화재 감지 리스너를 시작하고,
    서버 종료 시 관련 리소스를 순서대로 종료한다.
    """
    # MAVLink 메시지를 소비할 Redis 스트림 컨슈머를 생성하고 시작한다.
    runtime.consumer = RedisStreamConsumer(
        redis_host=os.getenv("REDIS_HOST", "redis"),
        redis_port=int(os.getenv("REDIS_PORT", "6379")),
        stream_key=os.getenv("STREAM_KEY", "mystream"),
        group=os.getenv("CONSUMER_GROUP", "mygroup"),
        consumer=None,
    )
    await runtime.consumer.start()

    # 앱 전역에서 사용할 Redis 클라이언트를 초기화한다.
    runtime.redis_client = redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=0,
        decode_responses=True,
    )

    # 화재 감지 스트림을 실시간으로 감시하는 리스너를 생성하고 시작한다.
    runtime.fire_listener = FireDetectListener(
        redis_client=runtime.redis_client,
        raw_image_dir=runtime.RAW_IMAGE_DIR,
        stream_key=os.getenv("RAW_STREAM_KEY", "fire_detect"),
        block_ms=int(os.getenv("FIRE_DETECT_BLOCK_MS", "5000")),
    )
    await runtime.fire_listener.start()

    # 여기서부터 앱이 실제 요청을 처리한다.
    yield

    # 서버 종료 시 시작했던 리소스를 정리한다.
    if runtime.fire_listener:
        await runtime.fire_listener.stop()
    if runtime.consumer:
        await runtime.consumer.stop()
    if runtime.redis_client:
        runtime.redis_client.close()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_v1_router)

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.redis_consumer import RedisStreamConsumer


# Redis Streams 컨슈머 인스턴스
consumer: RedisStreamConsumer = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기 관리"""
    # 시작 시 실행
    global consumer
    
    # Redis Streams 컨슈머 생성 및 시작
    # consumer 파라미터를 None으로 하면 자동으로 고유한 이름 생성
    consumer = RedisStreamConsumer(
        redis_host=os.getenv("REDIS_HOST", "redis"),  # Docker: "redis", 로컬: "localhost"
        redis_port=int(os.getenv("REDIS_PORT", "6379")),
        stream_key=os.getenv("STREAM_KEY", "mystream"),
        group=os.getenv("CONSUMER_GROUP", "mygroup"),
        consumer=None  # None이면 자동으로 고유한 이름 생성 (환경 변수 CONSUMER_NAME 우선)
    )
    
    await consumer.start()
    print("백그라운드 태스크 시작됨")
    
    yield
    
    # 종료 시 실행
    if consumer:
        await consumer.stop()
    print("백그라운드 태스크 중지됨")


app = FastAPI(lifespan=lifespan)


@app.get("/")
def root():
    return {"msg": "root"}


@app.get("/health")
def health():
    """헬스 체크"""
    return {
        "status": "healthy",
        "consumer_running": consumer.is_running if consumer else False,
        "consumer_name": consumer.consumer if consumer else None
    }
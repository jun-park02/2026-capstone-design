import os
from contextlib import asynccontextmanager
import redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app import app_state
from app.api.v1.routers import router as api_v1_router
from app.fire_detect_listener import FireDetectListener
from app.redis_consumer import RedisStreamConsumer
from prometheus_fastapi_instrumentator import Instrumentator


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
    app_state.consumer = RedisStreamConsumer(
        redis_host=envs["redis_host"],
        redis_port=int(envs["redis_port"]),
        stream_key=envs["drone_stream_key"],
        group=envs["group"],
        consumer=None,
    )
    await app_state.consumer.start()

    # redis 클라이언트(앱 전역에서 사용) 초기화
    app_state.redis_client = redis.Redis(
        host=envs["redis_host"],
        port=int(envs["redis_port"]),
        db=0,
        decode_responses=True,
    )

    # fire redis stream 리스너를 생성 및 시작
    app_state.fire_listener = FireDetectListener(
        redis_client=app_state.redis_client,
        raw_image_dir=app_state.RAW_IMAGE_DIR,
        stream_key=envs["fire_stream_key"],
        block_ms=int(envs["block_ms"]),
    )
    await app_state.fire_listener.start()

    yield

    # 서버 종료 시 시작했던 리소스 정리
    if app_state.fire_listener:
        await app_state.fire_listener.stop()
    if app_state.consumer:
        await app_state.consumer.stop()
    if app_state.redis_client:
        app_state.redis_client.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router)

Instrumentator(  # HTTP 요청 수와 응답 시간 등을 측정하는 계측 객체를 생성한다.
    should_group_status_codes=False,  # 상태 코드를 2xx 등으로 묶지 않고 200, 400, 500 등으로 구분한다.
    excluded_handlers=[r"^/metrics$"],  # /metrics 경로와 정확히 일치하는 수집 요청은 HTTP 통계에서 제외한다.
).instrument(app).expose(  # 앱에 계측 미들웨어를 추가하고, 수집한 지표를 제공하는 엔드포인트를 등록한다.
    app,  # 지표 조회 엔드포인트를 등록할 FastAPI 앱을 지정한다.
    endpoint="/metrics",  # Prometheus가 지표를 읽어 갈 URL 경로를 지정한다.
    include_in_schema=False,  # OpenAPI 스키마와 Swagger 문서에서 숨긴다. 실제 접근을 차단하지는 않는다.
)

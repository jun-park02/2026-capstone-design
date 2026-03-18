import asyncio
import json

import redis


class FireDetectListener:
    """fire_detect Redis Stream 리스너."""

    def __init__(
        self,
        redis_client: redis.Redis,
        stream_key: str = "fire_detect",
        block_ms: int = 5000,
    ):
        self.redis_client = redis_client
        self.stream_key = stream_key
        self.block_ms = block_ms

        self.is_running = False
        self.last_event: dict | None = None
        self.last_event_id: str | None = None
        self._task: asyncio.Task | None = None

    async def _watch_loop(self):
        last_id = "$"  # 리스너 시작 이후에 들어온 새 이벤트만 수신
        self.is_running = True

        while self.is_running:
            try:
                loop = asyncio.get_event_loop()
                # redis-py의 xread는 동기 함수라 이벤트 루프를 막지 않도록
                # 기본 스레드 풀에서 실행하고 여기서는 결과만 await 한다.
                resp = await loop.run_in_executor(
                    None,
                    lambda: self.redis_client.xread(
                        streams={self.stream_key: last_id},
                        count=1,
                        block=self.block_ms,
                    ),
                )

                if not resp:
                    continue

                for _, messages in resp:
                    for msg_id, fields in messages:
                        payload_raw = fields.get("payload")
                        payload = json.loads(payload_raw) if payload_raw else None
                        s3_image_url = payload.get("s3_image_url") if payload else None

                        # 마지막 이벤트를 메모리에 캐시해 /raw/latest/live 에서
                        # Redis 재조회 없이 바로 응답할 수 있게 한다.
                        self.last_event_id = msg_id
                        self.last_event = {
                            "id": msg_id,
                            "stream_key": self.stream_key,
                            "data": payload,
                            "s3_image_url": s3_image_url,
                        }
                        last_id = msg_id
                        print(f"[FIRE-DETECT-LISTENER] 새 이벤트 수신: {msg_id}")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(f"[FIRE-DETECT-LISTENER] 수신 오류: {exc}")
                await asyncio.sleep(1)

    async def start(self):
        if self._task and not self._task.done():
            return
        # FastAPI lifespan에서 백그라운드 태스크로 계속 실행된다.
        self._task = asyncio.create_task(self._watch_loop())

    async def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

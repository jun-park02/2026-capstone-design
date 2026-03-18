import asyncio
import json
import mimetypes
import os

import boto3
import redis


class FireDetectListener:
    """fire_detect Redis Stream 리스너."""

    def __init__(
        self,
        redis_client: redis.Redis,
        raw_image_dir: str,
        raw_image_url_prefix: str,
        stream_key: str = "fire_detect",
        block_ms: int = 5000,
    ):
        self.redis_client = redis_client
        self.raw_image_dir = raw_image_dir
        self.raw_image_url_prefix = raw_image_url_prefix
        self.stream_key = stream_key
        self.block_ms = block_ms

        self.is_running = False
        self.last_event: dict | None = None
        self.last_event_id: str | None = None
        self._task: asyncio.Task | None = None
        self._s3_client = None

    def build_image_url(self, payload: dict | None) -> str | None:
        """이벤트 payload에서 이미지 파일명을 찾아서 이미지 URL을 반환."""
        if not payload:
            return None
        image_name = payload.get("image_name")
        if not image_name and payload.get("image_path"):
            image_name = os.path.basename(payload["image_path"])
        if not image_name:
            return None
        return f"{self.raw_image_url_prefix}/{image_name}"

    def _get_image_name(self, payload: dict | None) -> str | None:
        if not payload:
            return None
        image_name = payload.get("image_name")
        if not image_name and payload.get("image_path"):
            image_name = os.path.basename(payload["image_path"])
        return image_name

    def _get_local_image_path(self, payload: dict | None) -> str | None:
        if not payload:
            return None
        image_path = payload.get("image_path")
        if image_path and os.path.exists(image_path):
            return image_path

        image_name = self._get_image_name(payload)
        if not image_name:
            return None

        candidate = os.path.join(self.raw_image_dir, image_name)
        if os.path.exists(candidate):
            return candidate
        return None

    def _build_s3_url(self, bucket: str, key: str) -> str:
        public_base_url = os.getenv("AWS_S3_PUBLIC_BASE_URL")
        if public_base_url:
            return f"{public_base_url.rstrip('/')}/{key}"
        region = os.getenv("AWS_REGION", "ap-northeast-2")
        return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"

    def _create_s3_client(self):
        if self._s3_client:
            return self._s3_client

        client_kwargs = {}
        region = os.getenv("AWS_REGION")
        endpoint_url = os.getenv("AWS_S3_ENDPOINT_URL")
        if region:
            client_kwargs["region_name"] = region
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url

        self._s3_client = boto3.client("s3", **client_kwargs)
        return self._s3_client

    def _upload_image_to_s3_sync(self, local_path: str, image_name: str) -> str | None:
        bucket = os.getenv("AWS_S3_BUCKET")
        if not bucket:
            return None

        key_prefix = os.getenv("AWS_S3_KEY_PREFIX", "fire-detect").strip("/")
        s3_key = f"{key_prefix}/{image_name}" if key_prefix else image_name

        client = self._create_s3_client()
        content_type, _ = mimetypes.guess_type(local_path)
        if content_type:
            client.upload_file(local_path, bucket, s3_key, ExtraArgs={"ContentType": content_type})
        else:
            client.upload_file(local_path, bucket, s3_key)

        return self._build_s3_url(bucket, s3_key)

    async def _maybe_upload_fire_image_to_s3(self, payload: dict | None) -> str | None:
        """수신된 화재 이벤트 이미지가 있으면 S3로 업로드 후 URL 반환."""
        enabled = os.getenv("S3_UPLOAD_ENABLED", "true").lower() == "true"
        if not enabled:
            return None

        image_name = self._get_image_name(payload)
        local_path = self._get_local_image_path(payload)
        if not image_name or not local_path:
            return None

        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None,
                lambda: self._upload_image_to_s3_sync(local_path, image_name),
            )
        except Exception as exc:
            print(f"[FIRE-DETECT-LISTENER] S3 업로드 실패: {exc}")
            return None

    async def _watch_loop(self):
        last_id = "$"  # 시작 이후 신규 이벤트만 수신
        self.is_running = True

        while self.is_running:
            try:
                loop = asyncio.get_event_loop()
                # redis-py의 xread는 동기 함수라 이벤트 루프를 막지 않도록
                # 기본 스레드 풀에서 실행하고 여기서는 결과만 await 한다.
                resp = await loop.run_in_executor(
                    None,
                    lambda: self.redis_client.xread(
                        # last_id 이후에 들어온 메시지를 1개씩 읽는다.
                        # 처음 값이 "$" 이므로 리스너 시작 이후의 새 이벤트만 받는다.
                        streams={self.stream_key: last_id},
                        count=1,
                        # 새 이벤트가 없으면 block_ms 동안 기다렸다가 빈 응답을 준다.
                        block=self.block_ms,
                    ),
                )

                if not resp:
                    continue

                for _, messages in resp:
                    for msg_id, fields in messages:
                        payload_raw = fields.get("payload")
                        payload = json.loads(payload_raw) if payload_raw else None

                        s3_image_url = await self._maybe_upload_fire_image_to_s3(payload)
                        if payload is not None and s3_image_url:
                            payload["s3_image_url"] = s3_image_url

                        self.last_event_id = msg_id
                        self.last_event = {
                            "id": msg_id,
                            "stream_key": self.stream_key,
                            "data": payload,
                            "image_url": self.build_image_url(payload),
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
        self._task = asyncio.create_task(self._watch_loop())

    async def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

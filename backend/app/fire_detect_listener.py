import asyncio
import hashlib
import json
import mimetypes
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import boto3
import redis
from sqlalchemy import select

from app.db import SessionLocal
from app.fire_confirmation import send_confirmation_emails_for_event
from app.models import FireEvent, FireEventImage


class FireDetectListener:
    """fire_detect Redis Stream 리스너."""

    def __init__(
        self,
        redis_client: redis.Redis,
        raw_image_dir: str,
        stream_key: str = "fire_detect",
        block_ms: int = 5000,
    ):
        self.redis_client = redis_client
        self.raw_image_dir = raw_image_dir
        self.stream_key = stream_key
        self.block_ms = block_ms

        self.is_running = False
        self.last_event: dict | None = None
        self.last_event_id: str | None = None
        self._task: asyncio.Task | None = None
        self._s3_client = None

    def _normalize_image_format(self, image_format: Any) -> str:
        """지원하는 이미지 포맷으로 정규화."""
        image_format = str(image_format or "jpg").lower()
        if image_format not in ("jpg", "jpeg", "png", "webp"):
            return "jpg"
        return image_format

    def _build_image_name(self, payload: dict[str, Any]) -> str:
        """이벤트 payload 기준으로 파일명을 만든다."""
        image_name = payload.get("image_name")
        if image_name:
            return str(image_name)

        image_format = self._normalize_image_format(payload.get("image_format"))
        return f"{payload['event_id']}_{payload['image_id']}.{image_format}"

    def _get_local_image_path(self, payload: dict[str, Any]) -> str:
        """공유 볼륨에 저장된 이미지 파일 경로를 찾는다."""
        image_path = payload.get("image_path")
        if image_path and os.path.exists(image_path):
            return image_path

        image_name = self._build_image_name(payload)
        candidate = os.path.join(self.raw_image_dir, image_name)
        if os.path.exists(candidate):
            return candidate

        raise FileNotFoundError(f"image file not found: {image_name}")

    def _build_s3_url(self, bucket: str, key: str) -> str:
        """버킷/키를 외부 접근용 URL로 변환."""
        public_base_url = os.getenv("AWS_S3_PUBLIC_BASE_URL")
        if public_base_url:
            return f"{public_base_url.rstrip('/')}/{key}"

        region = os.getenv("AWS_REGION", "ap-northeast-2")
        return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"

    def _create_s3_client(self):
        """S3 클라이언트를 재사용한다."""
        if self._s3_client is not None:
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

    def _parse_datetime(self, value: Any) -> datetime | None:
        """payload의 시간 문자열을 datetime으로 변환."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value

        value = str(value).strip()
        if not value:
            return None

        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")

        if dt.tzinfo is not None:
            dt = dt.astimezone(UTC).replace(tzinfo=None)
        return dt

    def _to_decimal(self, value: Any) -> Decimal | None:
        """숫자 payload를 Decimal로 변환."""
        if value is None or value == "":
            return None
        return Decimal(str(value))

    def _upload_image_to_s3_sync(self, local_path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
        """공유 볼륨의 이미지를 S3에 업로드하고 메타데이터를 반환."""
        bucket = os.getenv("AWS_S3_BUCKET")
        if not bucket:
            raise RuntimeError("AWS_S3_BUCKET is not configured")

        image_name = self._build_image_name(payload)
        key_prefix = os.getenv("AWS_S3_KEY_PREFIX", "fire-detect").strip("/")
        object_key = f"{key_prefix}/{image_name}" if key_prefix else image_name

        with open(local_path, "rb") as image_file:
            image_bytes = image_file.read()

        content_type, _ = mimetypes.guess_type(local_path)
        kwargs = {
            "Bucket": bucket,
            "Key": object_key,
            "Body": image_bytes,
        }
        if content_type:
            kwargs["ContentType"] = content_type

        response = self._create_s3_client().put_object(**kwargs)
        s3_meta = {
            "s3_bucket": bucket,
            "s3_object_key": object_key,
            "s3_image_url": self._build_s3_url(bucket, object_key),
            "s3_etag": response.get("ETag"),
            "s3_object_version_id": response.get("VersionId"),
            "s3_upload_status": "uploaded",
            "s3_upload_error": None,
        }
        return s3_meta, image_bytes

    def _save_event_to_db_sync(
        self,
        msg_id: str,
        payload: dict[str, Any],
        local_path: str,
        image_bytes: bytes | None,
        s3_meta: dict[str, Any] | None,
        upload_error: str | None,
    ) -> dict[str, Any]:
        """화재 이벤트와 이미지 메타데이터를 DB에 upsert."""
        session = SessionLocal()
        try:
            event = session.scalar(select(FireEvent).where(FireEvent.event_id == str(payload["event_id"])))
            if event is None:
                event = FireEvent(event_id=str(payload["event_id"]))
                session.add(event)

            event.redis_stream_id = msg_id
            event.received_at = self._parse_datetime(payload.get("received_at")) or datetime.utcnow()
            event.captured_at = self._parse_datetime(payload.get("captured_at"))
            event.lat = self._to_decimal(payload.get("lat"))
            event.lon = self._to_decimal(payload.get("lon"))
            event.alt = self._to_decimal(payload.get("alt"))
            event.confidence = self._to_decimal(payload.get("confidence"))
            event.src_ip = payload.get("src_ip")
            event.src_port = payload.get("src_port")
            event.dst_port = payload.get("dst_port")

            stored_payload = dict(payload)
            if s3_meta:
                stored_payload.update(s3_meta)
            if upload_error:
                stored_payload["s3_upload_status"] = "failed"
                stored_payload["s3_upload_error"] = upload_error
            event.raw_payload = stored_payload

            session.flush()

            image = session.scalar(
                select(FireEventImage).where(
                    FireEventImage.fire_event_id == event.id,
                    FireEventImage.image_uid == str(payload["image_id"]),
                )
            )
            if image is None:
                image = FireEventImage(
                    fire_event_id=event.id,
                    image_uid=str(payload["image_id"]),
                    original_filename=self._build_image_name(payload),
                )
                session.add(image)

            image.original_filename = self._build_image_name(payload)
            image.source_local_path = local_path
            image.file_ext = os.path.splitext(local_path)[1].lstrip(".").lower() or self._normalize_image_format(
                payload.get("image_format")
            )
            image.content_type = mimetypes.guess_type(local_path)[0]
            image.file_size_bytes = len(image_bytes) if image_bytes is not None else os.path.getsize(local_path)
            image.checksum_sha256 = (
                hashlib.sha256(image_bytes).hexdigest() if image_bytes is not None else None
            )
            image.chunk_total = payload.get("chunk_total")
            image.storage_provider = "s3"

            if s3_meta:
                image.bucket = s3_meta.get("s3_bucket")
                image.object_key = s3_meta.get("s3_object_key")
                image.object_version_id = s3_meta.get("s3_object_version_id")
                image.etag = s3_meta.get("s3_etag")
                image.upload_status = "uploaded"
                image.upload_error = None
                image.uploaded_at = datetime.utcnow()
            else:
                image.bucket = None
                image.object_key = None
                image.object_version_id = None
                image.etag = None
                image.upload_status = "failed"
                image.upload_error = upload_error
                image.uploaded_at = None

            session.commit()

            return {
                "db_save_status": "saved",
                "db_fire_event_pk": event.id,
                "db_fire_event_image_pk": image.id,
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _process_event_sync(self, msg_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Redis 이벤트를 S3 업로드 + DB 저장까지 처리한다."""
        local_path = self._get_local_image_path(payload)
        processed_payload = dict(payload)

        s3_meta = None
        upload_error = None
        image_bytes = None

        try:
            s3_meta, image_bytes = self._upload_image_to_s3_sync(local_path, payload)
            processed_payload.update(s3_meta)
        except Exception as exc:
            upload_error = str(exc)
            processed_payload["s3_upload_status"] = "failed"
            processed_payload["s3_upload_error"] = upload_error

        try:
            db_meta = self._save_event_to_db_sync(
                msg_id=msg_id,
                payload=processed_payload,
                local_path=local_path,
                image_bytes=image_bytes,
                s3_meta=s3_meta,
                upload_error=upload_error,
            )
            processed_payload.update(db_meta)
        except Exception as exc:
            processed_payload["db_save_status"] = "failed"
            processed_payload["db_save_error"] = str(exc)

        if processed_payload.get("db_save_status") == "saved":
            session = SessionLocal()
            try:
                event = session.get(FireEvent, processed_payload.get("db_fire_event_pk"))
                if event is not None:
                    processed_payload.update(send_confirmation_emails_for_event(session, event))
            except Exception as exc:
                session.rollback()
                processed_payload["confirmation_email_status"] = "failed"
                processed_payload["confirmation_email_reason"] = str(exc)
            finally:
                session.close()

        return {
            "id": msg_id,
            "stream_key": self.stream_key,
            "data": processed_payload,
            "s3_image_url": processed_payload.get("s3_image_url"),
        }

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
                        if payload is None:
                            continue

                        processed_event = await loop.run_in_executor(
                            None,
                            lambda msg_id=msg_id, payload=payload: self._process_event_sync(msg_id, payload),
                        )

                        # 마지막 이벤트를 메모리에 캐시해 /raw/latest/live 에서
                        # Redis 재조회 없이 바로 응답할 수 있게 한다.
                        self.last_event_id = msg_id
                        self.last_event = processed_event
                        last_id = msg_id
                        print(f"[FIRE-DETECT-LISTENER] 새 이벤트 수신 및 처리 완료: {msg_id}")
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

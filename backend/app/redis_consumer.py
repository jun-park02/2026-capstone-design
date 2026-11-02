import redis
import json
import asyncio
import os
import socket
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import insert

from app.db import SessionLocal
from app.models import DroneTelemetry
from app.realtime import drone_position_hub


DRONE_PATH_IDS_KEY = os.getenv("DRONE_PATH_IDS_KEY", "drone:path:ids")
DRONE_PATH_KEY_PREFIX = os.getenv("DRONE_PATH_KEY_PREFIX", "drone:path")
DRONE_STATUS_KEY_PREFIX = os.getenv("DRONE_STATUS_KEY_PREFIX", "drone:status")
DRONE_PATH_MAX_POINTS = int(os.getenv("DRONE_PATH_MAX_POINTS", "1000"))
DRONE_PATH_TTL_SEC = int(os.getenv("DRONE_PATH_TTL_SEC", "86400"))
DRONE_TELEMETRY_DB_ENABLED = os.getenv("DRONE_TELEMETRY_DB_ENABLED", "true").lower() not in {
    "0",
    "false",
    "no",
}


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _normalize_coordinate(value: Any, *, max_abs: float, scale: float = 1e7) -> float | None:
    coordinate = _to_float(value)
    if coordinate is None:
        return None
    if abs(coordinate) > max_abs:
        coordinate = coordinate / scale
    if abs(coordinate) > max_abs:
        return None
    return coordinate


def _normalize_millimeters(value: Any) -> float | None:
    distance = _to_float(value)
    if distance is None:
        return None
    return distance / 1000


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value

    if value is not None:
        text = str(value).strip()
        if text:
            try:
                if text.endswith("Z"):
                    text = text[:-1] + "+00:00"
                parsed = datetime.fromisoformat(text)
            except ValueError:
                try:
                    parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    parsed = None
            if parsed is not None:
                if parsed.tzinfo is not None:
                    return parsed.astimezone(UTC).replace(tzinfo=None)
                return parsed

    return datetime.utcnow()


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def generate_consumer_name(base_name: str = "fastapi-consumer") -> str:
    """고유한 컨슈머 이름 생성
    
    여러 worker 인스턴스가 각각 고유한 이름을 가지도록:
    1. 환경 변수 CONSUMER_NAME이 있으면 사용
    2. 없으면 호스트명 + 프로세스 ID + UUID 조합
    """
    # 환경 변수로 명시적으로 지정된 경우
    env_name = os.getenv("CONSUMER_NAME")
    if env_name:
        return env_name
    
    # 자동 생성: 호스트명-프로세스ID-UUID
    hostname = socket.gethostname()
    pid = os.getpid()
    unique_id = str(uuid.uuid4())[:8]  # UUID 앞 8자리만 사용
    return f"{base_name}-{hostname}-{pid}-{unique_id}"


class RedisStreamConsumer:
    """Redis Streams에서 데이터를 읽는 컨슈머"""
    
    def __init__(
        self,
        redis_host: Optional[str] = None,
        redis_port: int = 6379,
        stream_key: str = "drone_telemetry",
        group: str = "mygroup",
        consumer: Optional[str] = None,
        batch_size: int = 100  # 한 번에 가져올 메시지 수
    ):
        # 환경 변수에서 Redis 호스트 가져오기 (없으면 기본값)
        if redis_host is None:
            redis_host = os.getenv("REDIS_HOST", "redis")
        
        # 배치 크기: 환경 변수 또는 파라미터
        if batch_size == 100:  # 기본값인 경우 환경 변수 확인
            batch_size = int(os.getenv("REDIS_BATCH_SIZE", "100"))
        
        # 컨슈머 이름: 명시적으로 지정하거나 자동 생성
        if consumer is None:
            consumer = generate_consumer_name()
        self.redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=0,
            decode_responses=True
        )
        self.stream_key = stream_key
        self.group = group
        self.consumer = consumer
        self.batch_size = batch_size
        # 실행 주기 설정 (밀리초)
        self.block_timeout = int(os.getenv("REDIS_BLOCK_TIMEOUT", "5000"))  # 메시지 없을 때 대기 시간
        self.poll_interval = float(os.getenv("REDIS_POLL_INTERVAL", "0.01"))  # 메시지 처리 후 대기 시간
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

    def _drone_path_key(self, system_id: int | str) -> str:
        return f"{DRONE_PATH_KEY_PREFIX}:{system_id}"

    def _drone_status_key(self, system_id: int | str) -> str:
        return f"{DRONE_STATUS_KEY_PREFIX}:{system_id}"

    def _latest_drone_status(self, system_id: int | str) -> dict[str, Any]:
        status = self.redis_client.hgetall(self._drone_status_key(system_id))
        if not status:
            return {}

        return {
            "vehicle_status": status.get("vehicle_status") or None,
            "armed": _to_bool(status.get("armed")),
            "flight_enable": _to_bool(status.get("flight_enable")),
            "system_status": _to_int(status.get("system_status")),
            "system_status_name": status.get("system_status_name") or None,
            "status_seen_at": status.get("last_seen_at") or None,
        }

    def _cache_drone_position(self, msg_id: str, payload: dict[str, Any]) -> None:
        if payload.get("message_type") != "GLOBAL_POSITION_INT":
            return

        data = _parse_json(payload.get("data"))
        if not isinstance(data, dict):
            return

        lat = _normalize_coordinate(data.get("lat"), max_abs=90)
        lon = _normalize_coordinate(data.get("lon"), max_abs=180)
        system_id = _to_int(payload.get("system_id"))
        if lat is None or lon is None or system_id is None:
            return

        component_id = _to_int(payload.get("component_id"))
        point = {
            "drone_id": str(system_id),
            "stream_id": msg_id,
            "timestamp": payload.get("timestamp"),
            "telemetry_at": payload.get("timestamp"),
            "system_id": system_id,
            "component_id": component_id,
            "lat": lat,
            "lon": lon,
            "alt": _normalize_millimeters(data.get("alt")),
            "relative_alt": _normalize_millimeters(data.get("relative_alt")),
            "va": _to_float(data.get("va")),
            "position": [lat, lon],
            "heading": _to_float(data.get("hdg")),
            "time_boot_ms": _to_int(data.get("time_boot_ms")),
            **self._latest_drone_status(system_id),
        }

        key = self._drone_path_key(system_id)
        pipe = self.redis_client.pipeline()
        pipe.sadd(DRONE_PATH_IDS_KEY, str(system_id))
        pipe.rpush(key, json.dumps(point, separators=(",", ":")))
        pipe.ltrim(key, -DRONE_PATH_MAX_POINTS, -1)
        pipe.expire(key, DRONE_PATH_TTL_SEC)
        pipe.expire(DRONE_PATH_IDS_KEY, DRONE_PATH_TTL_SEC)
        pipe.execute()
        drone_position_hub.publish(point)

    def _build_telemetry_row(self, msg_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized_payload = dict(payload)
        data = _parse_json(normalized_payload.get("data"))
        if isinstance(data, dict):
            normalized_payload["data"] = data
        else:
            data = {}

        message_type = str(payload.get("message_type") or data.get("mavpackettype") or "UNKNOWN")[:64]
        lat = _normalize_coordinate(data.get("lat"), max_abs=90)
        lon = _normalize_coordinate(data.get("lon"), max_abs=180)

        return {
            "redis_stream_id": msg_id,
            "message_type": message_type,
            "system_id": _to_int(payload.get("system_id")),
            "component_id": _to_int(payload.get("component_id")),
            "telemetry_at": _parse_datetime(payload.get("timestamp")),
            "lat": _to_decimal(lat),
            "lon": _to_decimal(lon),
            "alt": _to_decimal(_normalize_millimeters(data.get("alt"))),
            "relative_alt": _to_decimal(_normalize_millimeters(data.get("relative_alt"))),
            "heading": _to_decimal(_to_float(data.get("hdg"))),
            "time_boot_ms": _to_int(data.get("time_boot_ms")),
            "raw_payload": normalized_payload,
        }

    def _save_telemetry_rows(self, rows: list[dict[str, Any]]) -> None:
        if not DRONE_TELEMETRY_DB_ENABLED or not rows:
            return

        session = SessionLocal()
        try:
            session.execute(insert(DroneTelemetry).prefix_with("IGNORE"), rows)
            session.commit()
        except Exception as exc:
            session.rollback()
            print(f"Drone telemetry DB save failed: {exc}")
        finally:
            session.close()
    
    def ensure_consumer_group(self):
        """컨슈머 그룹이 없으면 생성"""
        try:
            self.redis_client.xgroup_create(
                self.stream_key,
                self.group,
                id="$",
                mkstream=True
            )
            print(f"컨슈머 그룹 생성됨: {self.group}")
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" in str(e):
                print(f"컨슈머 그룹이 이미 존재함: {self.group}")
            else:
                raise
    
    async def process_message(self, msg_id: str, fields: dict) -> tuple[bool, dict[str, Any] | None]:
        """메시지 처리"""
        try:
            payload = fields.get("payload")
            if payload:
                data = json.loads(payload)
                if isinstance(data, dict):
                    self._cache_drone_position(msg_id, data)
                    return True, self._build_telemetry_row(msg_id, data)
                return True, None
        except Exception as e:
            print(f"메시지 처리 오류: {e}")
            return False, None
        return False, None
    
    async def process_batch(self, messages: list):
        """메시지 배치 처리
        
        Args:
            messages: [(msg_id, fields), ...] 형태의 리스트
        
        Returns:
            처리 성공한 msg_id 리스트
        """
        processed_ids = []
        telemetry_rows: list[dict[str, Any]] = []
        
        # 모든 메시지 처리
        for msg_id, fields in messages:
            success, telemetry_row = await self.process_message(msg_id, fields)
            if success:
                processed_ids.append(msg_id)
            if telemetry_row:
                telemetry_rows.append(telemetry_row)

        self._save_telemetry_rows(telemetry_rows)
        
        return processed_ids
    
    async def consume_messages(self):
        """Redis Streams에서 메시지 읽기 (비동기, 배치 처리)"""
        self.ensure_consumer_group()
        
        while self.is_running:
            try:
                # xreadgroup은 동기 함수이므로 run_in_executor로 실행
                loop = asyncio.get_event_loop()
                resp = await loop.run_in_executor(
                    None,
                    lambda: self.redis_client.xreadgroup(
                        groupname=self.group,
                        consumername=self.consumer,
                        streams={self.stream_key: ">"},
                        count=self.batch_size,  # 배치 크기만큼 한 번에 가져오기
                        block=self.block_timeout  # 메시지 없을 때 대기 시간 (ms)
                    )
                )
                
                if not resp:
                    # 메시지가 없을 때 (block timeout까지 대기했지만 메시지 없음)
                    print(f"[대기 중] 메시지 없음 (timeout: {self.block_timeout}ms)")
                    continue
                
                # 모든 메시지 수집
                all_messages = []
                for stream_name, messages in resp:
                    all_messages.extend([(msg_id, fields) for msg_id, fields in messages])
                
                if not all_messages:
                    continue
                
                # 배치로 처리
                processed_ids = await self.process_batch(all_messages)
                
                # 배치로 ACK 처리
                if processed_ids:
                    await loop.run_in_executor(
                        None,
                        lambda: self._batch_ack(processed_ids)
                    )
                    print(f"[배치 처리] {len(processed_ids)}개 메시지 처리 및 ACK 완료")
                
                # 실패한 메시지 수
                failed_count = len(all_messages) - len(processed_ids)
                if failed_count > 0:
                    print(f"[배치 처리] {failed_count}개 메시지 처리 실패")
                
                # 메시지 처리 후 대기 시간 (다음 읽기까지의 간격)
                await asyncio.sleep(self.poll_interval)
                
            except Exception as e:
                print(f"컨슈머 오류: {e}")
                await asyncio.sleep(1)  # 오류 발생 시 1초 대기
    
    def _batch_ack(self, msg_ids: list):
        """여러 메시지를 한 번에 ACK 처리"""
        pipe = self.redis_client.pipeline()
        for msg_id in msg_ids:
            pipe.xack(self.stream_key, self.group, msg_id)
        pipe.execute()
    
    async def start(self):
        """컨슈머 시작"""
        if self.is_running:
            return
        
        self.is_running = True
        self._task = asyncio.create_task(self.consume_messages())
        print(f"Redis Streams 컨슈머 시작: {self.stream_key}/{self.group} (consumer: {self.consumer})")
    
    async def stop(self):
        """컨슈머 중지"""
        if not self.is_running:
            return
        
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        self.redis_client.close()
        print("Redis Streams 컨슈머 중지됨")


import redis
import json
import asyncio
import os
import socket
import uuid
from typing import Optional


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
        stream_key: str = "mystream",
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
    
    async def process_message(self, msg_id: str, fields: dict):
        """메시지 처리"""
        try:
            payload = fields.get("payload")
            if payload:
                data = json.loads(payload)
                return True
        except Exception as e:
            print(f"메시지 처리 오류: {e}")
            return False
    
    async def process_batch(self, messages: list):
        """메시지 배치 처리
        
        Args:
            messages: [(msg_id, fields), ...] 형태의 리스트
        
        Returns:
            처리 성공한 msg_id 리스트
        """
        processed_ids = []
        
        # 모든 메시지 처리
        for msg_id, fields in messages:
            success = await self.process_message(msg_id, fields)
            if success:
                processed_ids.append(msg_id)
        
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


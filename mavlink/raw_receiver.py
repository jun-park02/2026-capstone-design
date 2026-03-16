import base64
import json
import os
import socket
import time
from pathlib import Path
from typing import Any
import redis

UDP_PORT = int(os.getenv("UDP_PORT", "14551"))
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
STREAM_KEY = os.getenv("STREAM_KEY", "fire_detect")
IMAGE_SAVE_DIR = os.getenv("IMG_SAVE_DIR", "/app/images")
SESSION_TIMEOUT_SEC = int(os.getenv("SESSION_TIMEOUT_SEC", "20"))

def create_redis_client():
    """Redis 클라이언트를 생성하고 연결 상태를 확인"""
    try:
        client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            # 논리 DB 번호
            db=0,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        # 실패하면 예외 발생
        client.ping()
        print(f"[FIRE-DETECT-RX] Redis 연결 성공: {REDIS_HOST}:{REDIS_PORT}")
        return client
    except Exception as e:
        print(f"[FIRE-DETECT-RX] Redis 연결 실패: {e}")
        return None


def now_str() -> str:
    """현재 로컬 시간을 문자열(YYYY-mm-dd HH:MM:SS)로 반환"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


def decode_udp_payload(data: bytes) -> dict[str, Any] | None:
    """UDP 바이트 데이터를 UTF-8 JSON으로 파싱

    기대 패킷 형식 예시:
    {
      "event_id": "evt-001",
      "image_id": "img-001",
      "chunk_index": 0,
      "chunk_total": 10,
      "chunk_data": "<base64>",
      # T : 날짜와 시간을 구분
      # Z : UTC(한국 시간은 +9)
      "captured_at": "2026-03-15T10:00:00Z", 
      "lat": 36.69,
      "lon": 126.58,
      # 미터 단위
      "alt": 55.2,
      "confidence": 0.91,
      "image_format": "jpg"
    }
    """
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None

def validate_chunk_message(payload: dict[str, Any]) -> tuple[bool, str]:
    """청크 메시지 필수 키, 타입, 범위를 검증"""
    required = ["event_id", "image_id", "chunk_index", "chunk_total", "chunk_data"]
    for key in required:
        if key not in payload:
            return False, f"missing field: {key}"

    if not isinstance(payload["chunk_index"], int):
        return False, "chunk_index must be int"
    if not isinstance(payload["chunk_total"], int):
        return False, "chunk_total must be int"
    if payload["chunk_total"] <= 0:
        return False, "chunk_total must be > 0"
    if payload["chunk_index"] < 0 or payload["chunk_index"] >= payload["chunk_total"]:
        return False, "chunk_index out of range"
    if not isinstance(payload["chunk_data"], str):
        return False, "chunk_data must be base64 string"

    return True, ""

def cleanup_expired_sessions(sessions: dict[tuple[str, str, str, int], dict[str, Any]], now_ts: float):
    """타임아웃된 미완성 세션을 제거해 메모리 누적을 방지"""
    expired_keys = []
    for key, session in sessions.items():
        if now_ts - session["updated_at"] > SESSION_TIMEOUT_SEC:
            expired_keys.append(key)
    for key in expired_keys:
        session = sessions.pop(key)
        print(
            f"[FIRE-DETECT-RX] 세션 만료 삭제: event={session['event_id']} "
            f"image={session['image_id']} received={len(session['chunks'])}/{session['chunk_total']}"
        )


def save_image(session: dict[str, Any], image_bytes: bytes) -> str:
    """조립 완료된 이미지 바이트를 파일로 저장하고 경로를 반환"""
    image_dir = Path(IMAGE_SAVE_DIR)
    image_dir.mkdir(parents=True, exist_ok=True)

    image_format = str(session["meta"].get("image_format", "jpg")).lower()
    if image_format not in ("jpg", "jpeg", "png", "webp"):
        image_format = "jpg"

    file_name = f"{session['event_id']}_{session['image_id']}.{image_format}"
    file_path = image_dir / file_name
    file_path.write_bytes(image_bytes)
    return str(file_path)


def publish_completed_event(redis_client, session: dict[str, Any], image_path: str):
    """이미지 조립 완료 이벤트를 Redis Stream에 기록"""
    if not redis_client:
        return
    try:
        payload = {
            "received_at": now_str(),
            "event_id": session["event_id"],
            "image_id": session["image_id"],
            "captured_at": session["meta"].get("captured_at"),
            "lat": session["meta"].get("lat"),
            "lon": session["meta"].get("lon"),
            "alt": session["meta"].get("alt"),
            "confidence": session["meta"].get("confidence"),
            "image_format": session["meta"].get("image_format", "jpg"),
            "chunk_total": session["chunk_total"],
            "image_name": Path(image_path).name,
            "image_path": image_path,
            "src_ip": session["src_ip"],
            "src_port": session["src_port"],
            "dst_port": UDP_PORT,
        }
        msg_id = redis_client.xadd(
            STREAM_KEY,
            {"payload": json.dumps(payload, ensure_ascii=False)},
            maxlen=10000,
            approximate=True,
        )
        print(f"[FIRE-DETECT-RX] Redis Stream 저장(완료 이벤트): {msg_id}")
    except Exception as exc:
        print(f"[FIRE-DETECT-RX] Redis 저장 오류: {exc}")


def try_finalize_session(redis_client, sessions: dict[tuple[str, str, str, int], dict[str, Any]], session_key):
    """세션의 모든 청크 수신 시 이미지를 조립, 저장, 발행"""
    session = sessions.get(session_key)
    if not session:
        return

    if len(session["chunks"]) != session["chunk_total"]:
        return

    # python list comprehension
    # i: 0부터 session["chunk_total"]-1까지의 숫자
    # i not in session["chunks"]: session["chunks"]에 없는 숫자
    # missing: session["chunks"]에 없는 숫자들의 리스트
    missing = [i for i in range(session["chunk_total"]) if i not in session["chunks"]]
    if missing:
        return

    ordered = [session["chunks"][i] for i in range(session["chunk_total"])]
    image_bytes = b"".join(ordered)
    image_path = save_image(session, image_bytes)
    publish_completed_event(redis_client, session, image_path)

    print(
        f"[FIRE-DETECT-RX] 이미지 조립 완료: event={session['event_id']} "
        f"image={session['image_id']} bytes={len(image_bytes)} path={image_path}"
    )
    sessions.pop(session_key, None)


def main():
    """화재 감지 UDP 패킷을 수신해 이미지로 재조립하고 완료 이벤트를 발행"""
    # create_redis_client -> socket/bind -> sessions 상태 초기화 -> while 루프 진입
    # - Redis 연결/UDP 소켓 준비 후, 세션 저장소를 만들고 패킷 처리 루프를 시작한다.
    redis_client = create_redis_client()

    # AF_INET: IPv4 주소 체계
    # SOCK_DGRAM: UDP 통신
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    print(f"[FIRE-DETECT-RX] UDP 수신 시작: 0.0.0.0:{UDP_PORT}")
    print(f"[FIRE-DETECT-RX] Redis Stream: {STREAM_KEY}")
    print(f"[FIRE-DETECT-RX] 이미지 저장 경로: {IMAGE_SAVE_DIR}")

    # key: (event_id, image_id, src_ip, src_port)
    sessions: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    # unix timestamp
    last_cleanup_ts = time.time()

    # recvfrom -> decode_udp_payload -> validate_chunk_message -> base64.b64decode
    # -> try_finalize_session -> cleanup_expired_sessions(주기적)
    # - 수신/파싱/검증/복원 후 세션에 청크를 누적하고, 완료되면 이미지 저장과 Redis 발행을 수행한다.
    # - 마지막으로 주기적으로 타임아웃 세션을 정리해 메모리 누적을 방지한다.
    while True:
        # 65535: 최대 패킷 크기
        data, (src_ip, src_port) = sock.recvfrom(65535)
        payload = decode_udp_payload(data)
        # 1. JSON 파싱 실패 시 해당 패킷은 폐기하고 다음 패킷으로 진행
        if payload is None:
            print(f"[FIRE-DETECT-RX] JSON 파싱 실패: from={src_ip}:{src_port} size={len(data)}")
            continue

        # 2. 필수 키/타입/범위 검증 실패 시 해당 패킷은 처리하지 않음
        is_valid, desc = validate_chunk_message(payload)
        if not is_valid:
            print(f"[FIRE-DETECT-RX] 패킷 검증 실패: {desc}")
            continue

        # 3. 청크 조립에 필요한 기본 필드 추출
        event_id = str(payload["event_id"])
        image_id = str(payload["image_id"])
        chunk_index = payload["chunk_index"]
        chunk_total = payload["chunk_total"]
        chunk_data = payload["chunk_data"]

        # 4. base64 청크 복원 실패 시 해당 패킷은 폐기
        try:
            # validate=True: 청크 데이터가 base64 형식인지 검증
            chunk_bytes = base64.b64decode(chunk_data, validate=True)
        except Exception:
            print(f"[FIRE-DETECT-RX] base64 디코딩 실패: event={event_id} image={image_id} chunk={chunk_index}")
            continue

        # 5. 세션 키 기준으로 기존 세션 조회, 없으면 새 세션 생성
        key = (event_id, image_id, src_ip, src_port)
        if key not in sessions:
            sessions[key] = {
                "event_id": event_id,
                "image_id": image_id,
                "src_ip": src_ip,
                "src_port": src_port,
                "chunk_total": chunk_total,
                "chunks": {},
                "meta": {
                    "captured_at": payload.get("captured_at"),
                    "lat": payload.get("lat"),
                    "lon": payload.get("lon"),
                    "alt": payload.get("alt"),
                    "confidence": payload.get("confidence"),
                    "image_format": payload.get("image_format", "jpg"),
                },
                "updated_at": time.time(),
            }
        session = sessions[key]

        # 6. 같은 세션에서 chunk_total 값이 바뀌면 비정상 전송으로 판단하고 무시
        if session["chunk_total"] != chunk_total:
            print(
                f"[FIRE-DETECT-RX] chunk_total 불일치: event={event_id} image={image_id} "
                f"{session['chunk_total']} != {chunk_total}"
            )
            continue

        # 7. 청크 저장 (같은 index 재수신 시 최신 값으로 덮어씀) + 최신 수신 시각 갱신
        session["chunks"][chunk_index] = chunk_bytes
        session["updated_at"] = time.time()

        print(
            f"[FIRE-DETECT-RX] 청크 수신: event={event_id} image={image_id} "
            f"{chunk_index + 1}/{chunk_total} from={src_ip}:{src_port}"
        )

        # 8. 모든 청크가 모였는지 확인하고 완료 시 이미지 저장 + Redis 발행
        try_finalize_session(redis_client, sessions, key)

        # 9. 1초마다 타임아웃된 미완성 세션 정리
        now_ts = time.time()
        if now_ts - last_cleanup_ts >= 1.0:
            cleanup_expired_sessions(sessions, now_ts)
            last_cleanup_ts = now_ts


if __name__ == "__main__":
    main()

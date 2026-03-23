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
    """Redis 클라이언트를 생성하고 연결 상태를 확인."""
    try:
        client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=0,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        client.ping()
        print(f"[FIRE-DETECT-RX] Redis 연결 성공: {REDIS_HOST}:{REDIS_PORT}")
        return client
    except Exception as exc:
        print(f"[FIRE-DETECT-RX] Redis 연결 실패: {exc}")
        return None


def now_str() -> str:
    """현재 로컬 시간을 문자열(YYYY-mm-dd HH:MM:SS)로 반환."""
    return time.strftime("%Y-%m-%d %H:%M:%S")


def decode_udp_payload(data: bytes) -> dict[str, Any] | None:
    """UDP 바이트 데이터를 UTF-8 JSON으로 파싱."""
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


def validate_chunk_message(payload: dict[str, Any]) -> tuple[bool, str]:
    """청크 메시지 필수 필드 및 범위를 검증."""
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


def cleanup_expired_sessions(
    sessions: dict[tuple[str, str, str, int], dict[str, Any]],
    now_ts: float,
):
    """오랫동안 끝나지 않은 세션을 제거해 메모리 누수를 방지."""
    expired_keys = []
    for key, session in sessions.items():
        if now_ts - session["updated_at"] > SESSION_TIMEOUT_SEC:
            expired_keys.append(key)

    for key in expired_keys:
        session = sessions.pop(key)
        print(
            f"[FIRE-DETECT-RX] 세션 만료 및 제거: event={session['event_id']} "
            f"image={session['image_id']} received={len(session['chunks'])}/{session['chunk_total']}"
        )


def normalize_image_format(image_format: Any) -> str:
    """지원하는 이미지 포맷으로 정규화."""
    image_format = str(image_format or "jpg").lower()
    if image_format not in ("jpg", "jpeg", "png", "webp"):
        return "jpg"
    return image_format


def build_image_name(session: dict[str, Any]) -> str:
    """이벤트/이미지 ID를 기반으로 파일명을 생성."""
    image_format = normalize_image_format(session["meta"].get("image_format"))
    return f"{session['event_id']}_{session['image_id']}.{image_format}"


def save_image(session: dict[str, Any], image_bytes: bytes) -> str:
    """조립된 이미지 바이트를 공유 볼륨에 저장하고 경로를 반환."""
    image_dir = Path(IMAGE_SAVE_DIR)
    image_dir.mkdir(parents=True, exist_ok=True)

    image_name = build_image_name(session)
    image_path = image_dir / image_name
    image_path.write_bytes(image_bytes)
    return str(image_path)


def publish_completed_event(redis_client, session: dict[str, Any], image_path: str, image_bytes: bytes):
    """이미지 조립 완료 이벤트를 Redis Stream에 기록."""
    if not redis_client:
        return

    try:
        # FastAPI는 이 메타데이터만 Redis에서 받고,
        # 실제 이미지 파일은 공유 볼륨 경로로 읽어 S3 업로드와 DB 저장을 진행한다.
        payload = {
            "received_at": now_str(),
            "event_id": session["event_id"],
            "image_id": session["image_id"],
            "captured_at": session["meta"].get("captured_at"),
            "lat": session["meta"].get("lat"),
            "lon": session["meta"].get("lon"),
            "alt": session["meta"].get("alt"),
            "confidence": session["meta"].get("confidence"),
            "image_format": normalize_image_format(session["meta"].get("image_format")),
            "chunk_total": session["chunk_total"],
            "image_name": build_image_name(session),
            "image_path": image_path,
            "image_size_bytes": len(image_bytes),
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
        print(f"[FIRE-DETECT-RX] Redis Stream 추가 완료 이벤트: {msg_id}")
    except Exception as exc:
        print(f"[FIRE-DETECT-RX] Redis 저장 오류: {exc}")


def try_finalize_session(
    redis_client,
    sessions: dict[tuple[str, str, str, int], dict[str, Any]],
    session_key,
):
    """모든 청크가 모이면 이미지를 조립하고 Redis 이벤트를 발행."""
    session = sessions.get(session_key)
    if not session:
        return

    if len(session["chunks"]) != session["chunk_total"]:
        return

    missing = [i for i in range(session["chunk_total"]) if i not in session["chunks"]]
    if missing:
        return

    # chunk_index 순서대로 정렬해 원본 이미지 바이트를 복원한다.
    ordered = [session["chunks"][i] for i in range(session["chunk_total"])]
    image_bytes = b"".join(ordered)
    image_path = save_image(session, image_bytes)

    publish_completed_event(redis_client, session, image_path, image_bytes)

    print(
        f"[FIRE-DETECT-RX] 이미지 조립 완료, Redis 이벤트 발행: "
        f"event={session['event_id']} image={session['image_id']} bytes={len(image_bytes)} path={image_path}"
    )

    sessions.pop(session_key, None)


def main():
    """화재 감지 UDP 청크를 수신해 이미지를 조립하고 완료 이벤트를 발행."""
    redis_client = create_redis_client()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    print(f"[FIRE-DETECT-RX] UDP 수신 시작: 0.0.0.0:{UDP_PORT}")
    print(f"[FIRE-DETECT-RX] Redis Stream: {STREAM_KEY}")
    print(f"[FIRE-DETECT-RX] 이미지 저장 경로: {IMAGE_SAVE_DIR}")

    # key 하나가 "같은 이미지 전송 세션"을 뜻한다.
    sessions: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    last_cleanup_ts = time.time()

    while True:
        data, (src_ip, src_port) = sock.recvfrom(65535)
        payload = decode_udp_payload(data)
        if payload is None:
            print(f"[FIRE-DETECT-RX] JSON 파싱 실패: from={src_ip}:{src_port} size={len(data)}")
            continue

        is_valid, desc = validate_chunk_message(payload)
        if not is_valid:
            print(f"[FIRE-DETECT-RX] 패킷 검증 실패: {desc}")
            continue

        event_id = str(payload["event_id"])
        image_id = str(payload["image_id"])
        chunk_index = payload["chunk_index"]
        chunk_total = payload["chunk_total"]
        chunk_data = payload["chunk_data"]

        try:
            chunk_bytes = base64.b64decode(chunk_data, validate=True)
        except Exception:
            print(f"[FIRE-DETECT-RX] base64 디코드 실패: event={event_id} image={image_id} chunk={chunk_index}")
            continue

        # event/image/src 조합으로 세션을 묶어야 여러 이미지 전송이 동시에 와도 섞이지 않는다.
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

        # 같은 세션에서 총 청크 수가 바뀌면 비정상 전송으로 보고 무시한다.
        if session["chunk_total"] != chunk_total:
            print(
                f"[FIRE-DETECT-RX] chunk_total 불일치: event={event_id} image={image_id} "
                f"{session['chunk_total']} != {chunk_total}"
            )
            continue

        # 청크를 누적해두고, 매 수신마다 "모두 모였는지" 확인한다.
        session["chunks"][chunk_index] = chunk_bytes
        session["updated_at"] = time.time()

        print(
            f"[FIRE-DETECT-RX] 청크 수신: event={event_id} image={image_id} "
            f"{chunk_index + 1}/{chunk_total} from={src_ip}:{src_port}"
        )

        try_finalize_session(redis_client, sessions, key)

        # 오래 남아 있는 미완성 세션은 주기적으로 정리한다.
        now_ts = time.time()
        if now_ts - last_cleanup_ts >= 1.0:
            cleanup_expired_sessions(sessions, now_ts)
            last_cleanup_ts = now_ts


if __name__ == "__main__":
    main()

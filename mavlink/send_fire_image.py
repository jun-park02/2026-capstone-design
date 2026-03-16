import base64
import json
import socket
import time
import uuid
from pathlib import Path


def chunk_bytes(data: bytes, chunk_size: int):
    for i in range(0, len(data), chunk_size):
        yield data[i : i + chunk_size]


def detect_image_format(image_path: Path) -> str:
    ext = image_path.suffix.lower().replace(".", "")
    if ext in ("jpg", "jpeg", "png", "webp"):
        return ext
    return "jpg"

IMAGE_PATH = Path(r"C:\test\519196_gettyimages1270593514_590256.jpg")
TARGET_IP = "127.0.0.1"
TARGET_PORT = 14551
CHUNK_SIZE = 1200
DELAY_MS = 5

EVENT_ID = f"evt-{uuid.uuid4().hex[:12]}"
IMAGE_ID = f"img-{uuid.uuid4().hex[:12]}"
CAPTURED_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
LAT = 37.5665
LON = 126.9780
ALT = 50.0
CONFIDENCE = 0.9


def main():
    image_path = IMAGE_PATH
    if not image_path.exists():
        raise FileNotFoundError(f"이미지 파일을 찾을 수 없습니다: {image_path}")
    if not image_path.is_file():
        raise ValueError(f"파일이 아닙니다: {image_path}")
    if CHUNK_SIZE <= 0:
        raise ValueError("CHUNK_SIZE는 1 이상이어야 합니다.")
    if DELAY_MS < 0:
        raise ValueError("DELAY_MS는 0 이상이어야 합니다.")

    image_bytes = image_path.read_bytes()
    chunks = list(chunk_bytes(image_bytes, CHUNK_SIZE))
    chunk_total = len(chunks)
    image_format = detect_image_format(image_path)

    if chunk_total == 0:
        raise ValueError("빈 파일은 전송할 수 없습니다.")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dst = (TARGET_IP, TARGET_PORT)

    print(
        f"[FIRE-TX] start image={image_path} size={len(image_bytes)} "
        f"chunks={chunk_total} dst={TARGET_IP}:{TARGET_PORT}"
    )
    print(
        f"[FIRE-TX] event_id={EVENT_ID} image_id={IMAGE_ID} "
        f"lat={LAT} lon={LON} alt={ALT} conf={CONFIDENCE}"
    )

    delay_sec = DELAY_MS / 1000.0
    for idx, chunk in enumerate(chunks):
        payload = {
            "event_id": EVENT_ID,
            "image_id": IMAGE_ID,
            "chunk_index": idx,
            "chunk_total": chunk_total,
            "chunk_data": base64.b64encode(chunk).decode("ascii"),
            "captured_at": CAPTURED_AT,
            "lat": LAT,
            "lon": LON,
            "alt": ALT,
            "confidence": CONFIDENCE,
            "image_format": image_format,
        }
        packet = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        sock.sendto(packet, dst)

        if idx == 0 or idx == chunk_total - 1 or (idx + 1) % 20 == 0:
            print(f"[FIRE-TX] sent {idx + 1}/{chunk_total}")

        if delay_sec > 0:
            time.sleep(delay_sec)

    sock.close()
    print("[FIRE-TX] done")


if __name__ == "__main__":
    main()

import json
import mimetypes
import os
import time
import uuid
from pathlib import Path
from urllib import error, request


# 업로드 테스트에 사용할 로컬 이미지 파일 경로
IMAGE_PATH = Path(os.getenv("IMAGE_PATH", r"C:\test\images.jpeg"))
# 이미지를 보낼 FastAPI 업로드 엔드포인트 URL
TARGET_URL = os.getenv("TARGET_URL", "http://127.0.0.1:14551/fire-detections/upload")

# 테스트 화재 이벤트 ID
EVENT_ID = os.getenv("EVENT_ID", f"evt-{uuid.uuid4().hex[:12]}")
# 테스트 이미지 ID
IMAGE_ID = os.getenv("IMAGE_ID", f"img-{uuid.uuid4().hex[:12]}")
# 이미지 촬영 시각
CAPTURED_AT = os.getenv("CAPTURED_AT", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1)))
# 화재 감지 위치의 위도
LAT = os.getenv("LAT", "37.5985")
# 화재 감지 위치의 경도
LON = os.getenv("LON", "126.9380")
# 화재 감지 위치의 고도
ALT = os.getenv("ALT", "50.0")
# 화재 감지 신뢰도
CONFIDENCE = os.getenv("CONFIDENCE", "0.9")
# 화재를 감지한 드론 ID
SYSTEM_ID = os.getenv("SYSTEM_ID", "1")
# 업로드 요청 응답을 기다릴 최대 시간
REQUEST_TIMEOUT_SEC = float(os.getenv("REQUEST_TIMEOUT_SEC", "30"))


def detect_image_format(image_path: Path) -> str:
    ext = image_path.suffix.lower().lstrip(".")
    if ext == "jpeg":
        return "jpg"
    if ext in {"jpg", "png", "webp"}:
        return ext
    return "jpg"


def build_multipart_body(
    fields: dict[str, str],
    *,
    file_field: str,
    file_path: Path,
    file_bytes: bytes,
    content_type: str,
) -> tuple[bytes, str]:
    boundary = f"----fire-detect-{uuid.uuid4().hex}"
    lines: list[bytes] = []

    for name, value in fields.items():
        lines.extend(
            [
                f"--{boundary}".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"),
                b"",
                str(value).encode("utf-8"),
            ]
        )

    lines.extend(
        [
            f"--{boundary}".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_path.name}"'
            ).encode("utf-8"),
            f"Content-Type: {content_type}".encode("utf-8"),
            b"",
            file_bytes,
            f"--{boundary}--".encode("utf-8"),
            b"",
        ]
    )
    return b"\r\n".join(lines), boundary


def main():
    image_path = IMAGE_PATH
    if not image_path.exists():
        raise FileNotFoundError(f"이미지 파일을 찾을 수 없습니다: {image_path}")
    if not image_path.is_file():
        raise ValueError(f"파일이 아닙니다: {image_path}")

    image_bytes = image_path.read_bytes()
    if not image_bytes:
        raise ValueError("빈 파일은 전송할 수 없습니다.")

    image_format = detect_image_format(image_path)
    content_type = mimetypes.guess_type(image_path.name)[0] or f"image/{image_format}"
    if content_type == "image/jpeg":
        image_format = "jpg"

    fields = {
        "event_id": EVENT_ID,
        "image_id": IMAGE_ID,
        "captured_at": CAPTURED_AT,
        "lat": LAT,
        "lon": LON,
        "alt": ALT,
        "confidence": CONFIDENCE,
        "system_id": SYSTEM_ID,
        "image_format": image_format,
    }
    body, boundary = build_multipart_body(
        fields,
        file_field="image",
        file_path=image_path,
        file_bytes=image_bytes,
        content_type=content_type,
    )

    print(
        f"[FIRE-TX] upload image={image_path} size={len(image_bytes)} "
        f"url={TARGET_URL}"
    )
    print(
        f"[FIRE-TX] event_id={EVENT_ID} image_id={IMAGE_ID} "
        f"lat={LAT} lon={LON} alt={ALT} conf={CONFIDENCE} system_id={SYSTEM_ID}"
    )

    req = request.Request(
        TARGET_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )

    try:
        with request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as response:
            response_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"업로드 실패: HTTP {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"업로드 서버에 연결할 수 없습니다: {exc}") from exc

    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        parsed = response_body

    print(f"[FIRE-TX] response={json.dumps(parsed, ensure_ascii=False)}")
    print("[FIRE-TX] done")


if __name__ == "__main__":
    main()

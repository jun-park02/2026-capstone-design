import json
import mimetypes
import uuid
from pathlib import Path
from urllib import request


TARGET_URL = "http://127.0.0.1:14551/heatmap/upload"
REQUEST_TIMEOUT_SEC = 30

HEATMAP_ID = f"heatmap-{uuid.uuid4().hex[:12]}"
X_MIN = "126.9700"
X_MAX = "126.9900"
Y_MIN = "37.5600"
Y_MAX = "37.5700"
OPACITY = "0.35"

IMAGE_PATHS = [
    Path(r"C:\test\heatmap-1780407770749_frame_000.png"),
    Path(r"C:\test\heatmap-1780407770749_frame_001.png"),
    Path(r"C:\test\heatmap-1780407770749_frame_002.png"),
    Path(r"C:\test\heatmap-1780407770749_frame_003.png"),
    Path(r"C:\test\heatmap-1780407770749_frame_004.png"),
    Path(r"C:\test\heatmap-1780407770749_frame_005.png"),
]


def build_multipart_body(
    fields: dict[str, str],
    files: list[tuple[str, Path, bytes, str]],
) -> tuple[bytes, str]:
    boundary = f"----heatmap-upload-{uuid.uuid4().hex}"
    lines: list[bytes] = []

    for name, value in fields.items():
        lines.extend(
            [
                f"--{boundary}".encode(),
                f'Content-Disposition: form-data; name="{name}"'.encode(),
                b"",
                value.encode(),
            ]
        )

    for field_name, file_path, file_bytes, content_type in files:
        lines.extend(
            [
                f"--{boundary}".encode(),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; '
                    f'filename="{file_path.name}"'
                ).encode(),
                f"Content-Type: {content_type}".encode(),
                b"",
                file_bytes,
            ]
        )

    lines.extend([f"--{boundary}--".encode(), b""])
    return b"\r\n".join(lines), boundary


def main():
    files = []
    for index, image_path in enumerate(IMAGE_PATHS):
        image_bytes = image_path.read_bytes()
        content_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
        files.append((f"image_{index}", image_path, image_bytes, content_type))

    meta_json = json.dumps(
        {
            "heatmap_id": HEATMAP_ID,
            "x_min": X_MIN,
            "x_max": X_MAX,
            "y_min": Y_MIN,
            "y_max": Y_MAX,
            "opacity": OPACITY,
        },
        ensure_ascii=False,
    )
    body, boundary = build_multipart_body({"meta_json": meta_json}, files)

    print(f"[HEATMAP-TX] upload url={TARGET_URL}")
    print(f"[HEATMAP-TX] heatmap_id={HEATMAP_ID} image_count={len(files)}")
    print(f"[HEATMAP-TX] coordinates=({X_MIN}, {Y_MIN}) -> ({X_MAX}, {Y_MAX})")

    req = request.Request(
        TARGET_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )

    with request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as response:
        response_body = response.read().decode("utf-8")

    print(f"[HEATMAP-TX] response={response_body}")


if __name__ == "__main__":
    main()

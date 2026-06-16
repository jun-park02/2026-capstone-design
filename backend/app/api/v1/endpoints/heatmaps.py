import asyncio
import json
import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from app import runtime


router = APIRouter(tags=["heatmaps"])

HEATMAP_STREAM_KEY = os.getenv("HEATMAP_STREAM_KEY", "heatmap")
HEATMAP_IMAGE_DIR = os.getenv("HEATMAP_IMAGE_DIR", "/app/images/heatmaps")
DEFAULT_HEATMAP_OPACITY = float(os.getenv("HEATMAP_OVERLAY_OPACITY", "0.35"))


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


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


def _sse_payload(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _heatmap_image_url(image_name: str) -> str:
    return f"/heatmaps/images/{quote(image_name, safe='')}"


def _heatmap_image_path(image_name: str) -> Path:
    if not image_name or "/" in image_name or "\\" in image_name:
        raise HTTPException(status_code=400, detail="invalid heatmap image name")

    root = Path(HEATMAP_IMAGE_DIR).resolve()
    image_path = (root / image_name).resolve()
    try:
        image_path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid heatmap image path") from exc

    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="heatmap image not found")
    return image_path


def _coordinates_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    coordinates = payload.get("coordinates")
    if isinstance(coordinates, dict):
        return coordinates

    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    x_min = _first_value(payload.get("x_min"), metadata.get("x_min"))
    x_max = _first_value(payload.get("x_max"), metadata.get("x_max"))
    y_min = _first_value(payload.get("y_min"), metadata.get("y_min"))
    y_max = _first_value(payload.get("y_max"), metadata.get("y_max"))
    if any(value is None or value == "" for value in (x_min, x_max, y_min, y_max)):
        return None

    return {
        "bottom_left": {"x": x_min, "y": y_min},
        "top_right": {"x": x_max, "y": y_max},
    }


def _format_heatmap_frame(frame: dict[str, Any], fallback_index: int) -> dict[str, Any] | None:
    image_name = frame.get("image_name")
    if not image_name:
        return None

    frame_index = _to_int(_first_value(frame.get("frame_index"), fallback_index)) or fallback_index
    prediction_minutes = _to_int(_first_value(frame.get("prediction_minutes"), (frame_index + 1) * 10))
    if prediction_minutes is None:
        prediction_minutes = (frame_index + 1) * 10
    return {
        "frame_index": frame_index,
        "image_name": str(image_name),
        "image_url": _heatmap_image_url(str(image_name)),
        "prediction_minutes": prediction_minutes,
        "label": frame.get("label") or f"{prediction_minutes}분 뒤 확산 예측 히트맵",
    }


def _format_heatmap_payload(stream_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    frames_raw = payload.get("frames")
    if not isinstance(frames_raw, list):
        frames_raw = payload.get("images")
    if not isinstance(frames_raw, list):
        frames_raw = []

    frames = [
        frame
        for index, raw_frame in enumerate(frames_raw)
        if isinstance(raw_frame, dict)
        for frame in [_format_heatmap_frame(raw_frame, index)]
        if frame is not None
    ]
    if not frames:
        image_name = payload.get("image_name")
        if image_name:
            frames = [
                {
                    "frame_index": 0,
                    "image_name": str(image_name),
                    "image_url": _heatmap_image_url(str(image_name)),
                    "prediction_minutes": 10,
                    "label": "10분 뒤 확산 예측 히트맵",
                }
            ]

    coordinates = _coordinates_from_payload(payload)
    if coordinates is None or not frames:
        return None

    return {
        "ok": True,
        "id": stream_id,
        "heatmap_id": payload.get("heatmap_id"),
        "coordinates": coordinates,
        "opacity": _first_value(payload.get("opacity"), DEFAULT_HEATMAP_OPACITY),
        "frames": sorted(frames, key=lambda frame: frame["frame_index"]),
        "received_at": payload.get("received_at"),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    }


def _payload_from_fields(fields: dict[str, Any]) -> dict[str, Any] | None:
    payload = _parse_json(fields.get("payload") if isinstance(fields, dict) else None)
    return payload if isinstance(payload, dict) else None


@router.get("/heatmaps/images/{image_name:path}")
def get_heatmap_image(image_name: str):
    image_path = _heatmap_image_path(image_name)
    media_type = mimetypes.guess_type(image_path.name)[0]
    return FileResponse(image_path, media_type=media_type)


@router.get("/heatmaps/stream")
async def stream_heatmaps(
    request: Request,
    heartbeat_sec: float = Query(15.0, ge=1, le=60),
    stream_key: str = Query(HEATMAP_STREAM_KEY, min_length=1),
):
    async def event_generator():
        if not runtime.redis_client:
            yield _sse_payload("heatmap", {"ok": False, "message": "Redis client not initialized"})
            return

        last_id = "$"
        latest_entries = runtime.redis_client.xrevrange(stream_key, count=1)
        if latest_entries:
            latest_id, fields = latest_entries[0]
            payload = _payload_from_fields(fields)
            if payload is not None:
                formatted = _format_heatmap_payload(latest_id, payload)
                if formatted is not None:
                    yield _sse_payload("heatmap", formatted)
                    last_id = latest_id

        block_ms = int(heartbeat_sec * 1000)
        loop = asyncio.get_event_loop()
        while not await request.is_disconnected():
            resp = await loop.run_in_executor(
                None,
                lambda: runtime.redis_client.xread(
                    streams={stream_key: last_id},
                    count=1,
                    block=block_ms,
                ),
            )
            if not resp:
                yield ": keep-alive\n\n"
                continue

            for _, messages in resp:
                for msg_id, fields in messages:
                    last_id = msg_id
                    payload = _payload_from_fields(fields)
                    if payload is None:
                        continue

                    formatted = _format_heatmap_payload(msg_id, payload)
                    if formatted is not None:
                        yield _sse_payload("heatmap", formatted)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

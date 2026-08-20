"""YOLO 图片 / 视频检测。"""
from __future__ import annotations

import base64
import threading
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from ultralytics import YOLO

from class_colors import DEFAULT_COLORS, hex_to_bgr

_model_cache: dict[str, YOLO] = {}
_cache_lock = threading.Lock()

video_jobs: dict[str, dict] = {}
video_jobs_lock = threading.Lock()


def get_yolo(weight: str) -> YOLO:
    key = str(Path(weight).resolve()) if Path(weight).exists() else weight
    with _cache_lock:
        if key not in _model_cache:
            _model_cache[key] = YOLO(weight)
        return _model_cache[key]


def _bgr_to_jpeg_b64(bgr: np.ndarray) -> str:
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        raise RuntimeError("编码失败")
    return base64.b64encode(buf.tobytes()).decode()


def _color_for(name: str, cls_id: int, color_map: dict[str, str] | None) -> str:
    if color_map and name in color_map:
        return color_map[name]
    return DEFAULT_COLORS[cls_id % len(DEFAULT_COLORS)]


def _draw_detections(bgr: np.ndarray, result, color_map: dict[str, str] | None = None) -> np.ndarray:
    plotted = bgr.copy()
    names = result.names or {}
    if result.boxes is None:
        return plotted
    for box in result.boxes:
        x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
        cls_id = int(box.cls[0])
        conf = float(box.conf[0])
        name = names.get(cls_id, str(cls_id))
        hex_c = _color_for(name, cls_id, color_map)
        color = hex_to_bgr(hex_c)
        cv2.rectangle(plotted, (x1, y1), (x2, y2), color, 2)
        label = f"{name} {conf:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        top = max(0, y1 - th - 8)
        cv2.rectangle(plotted, (x1, top), (x1 + tw + 6, y1), color, -1)
        cv2.putText(
            plotted, label, (x1 + 3, max(th + 2, y1 - 4)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA,
        )
    return plotted


def _collect_boxes(result, color_map: dict[str, str] | None = None) -> list[dict]:
    boxes = []
    if result.boxes is None:
        return boxes
    names = result.names or {}
    for box in result.boxes:
        xyxy = box.xyxy[0].tolist()
        cls_id = int(box.cls[0])
        name = names.get(cls_id, str(cls_id))
        boxes.append({
            "cls": name,
            "clsId": cls_id,
            "conf": round(float(box.conf[0]), 4),
            "xyxy": [round(x, 1) for x in xyxy],
            "color": _color_for(name, cls_id, color_map),
        })
    return boxes


def detect_image(
    weight: str,
    image_bytes: bytes,
    conf: float = 0.25,
    iou: float = 0.7,
    color_map: dict[str, str] | None = None,
) -> dict:
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    model = get_yolo(weight)
    result = model.predict(source=bgr, conf=conf, iou=iou, verbose=False)[0]
    plotted = _draw_detections(bgr, result, color_map)
    boxes = _collect_boxes(result, color_map)
    h, w = bgr.shape[:2]
    return {
        "width": w,
        "height": h,
        "count": len(boxes),
        "boxes": boxes,
        "image": "data:image/jpeg;base64," + _bgr_to_jpeg_b64(plotted),
    }


def detect_video(
    job_id: str,
    weight: str,
    src: str,
    dst: str,
    conf: float = 0.25,
    iou: float = 0.7,
    color_map: dict[str, str] | None = None,
):
    with video_jobs_lock:
        video_jobs[job_id] = {
            "status": "running",
            "processed": 0,
            "total": 0,
            "output": None,
            "error": None,
        }
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        with video_jobs_lock:
            video_jobs[job_id].update(status="failed", error="无法打开视频")
        return
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    with video_jobs_lock:
        video_jobs[job_id]["total"] = total
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(dst, fourcc, fps, (w, h))
    model = get_yolo(weight)
    processed = 0
    try:
        while True:
            ok_frame, frame = cap.read()
            if not ok_frame:
                break
            result = model.predict(source=frame, conf=conf, iou=iou, verbose=False)[0]
            writer.write(_draw_detections(frame, result, color_map))
            processed += 1
            if processed % 5 == 0 or processed == total:
                with video_jobs_lock:
                    video_jobs[job_id]["processed"] = processed
    except Exception as exc:  # noqa: BLE001
        with video_jobs_lock:
            video_jobs[job_id].update(status="failed", error=str(exc))
        return
    finally:
        cap.release()
        writer.release()
    with video_jobs_lock:
        video_jobs[job_id].update(
            status="done",
            processed=processed,
            output=Path(dst).name,
        )

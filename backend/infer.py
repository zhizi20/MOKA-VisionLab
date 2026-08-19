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


def detect_image(weight: str, image_bytes: bytes, conf: float = 0.25) -> dict:
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    model = get_yolo(weight)
    result = model.predict(source=bgr, conf=conf, verbose=False)[0]
    plotted = result.plot()
    boxes = []
    if result.boxes is not None:
        names = result.names or {}
        for box in result.boxes:
            xyxy = box.xyxy[0].tolist()
            cls_id = int(box.cls[0])
            boxes.append({
                "cls": names.get(cls_id, str(cls_id)),
                "clsId": cls_id,
                "conf": round(float(box.conf[0]), 4),
                "xyxy": [round(x, 1) for x in xyxy],
            })
    h, w = bgr.shape[:2]
    return {
        "width": w,
        "height": h,
        "count": len(boxes),
        "boxes": boxes,
        "image": "data:image/jpeg;base64," + _bgr_to_jpeg_b64(plotted),
    }


def detect_video(job_id: str, weight: str, src: str, dst: str, conf: float = 0.25):
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
            result = model.predict(source=frame, conf=conf, verbose=False)[0]
            writer.write(result.plot())
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

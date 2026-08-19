"""标注辅助：YOLO 预标 + Ultralytics MobileSAM 点选成框。"""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from PIL import Image
from ultralytics import SAM

from infer import get_yolo

_sam = None
_sam_lock = threading.Lock()


def get_sam() -> SAM:
    global _sam
    with _sam_lock:
        if _sam is None:
            _sam = SAM("mobile_sam.pt")
        return _sam


def _xyxy_to_yolo(x1, y1, x2, y2, width, height) -> dict:
    w = max(x2 - x1, 1.0)
    h = max(y2 - y1, 1.0)
    return {
        "cx": float(((x1 + x2) / 2) / width),
        "cy": float(((y1 + y2) / 2) / height),
        "w": float(w / width),
        "h": float(h / height),
    }


def _mask_xyxy(result) -> list[float] | None:
    if result.boxes is not None and len(result.boxes):
        return result.boxes.xyxy[0].tolist()
    if result.masks is None:
        return None
    xy = getattr(result.masks, "xy", None)
    if xy is not None and len(xy):
        pts = np.asarray(xy[0])
        if pts.size == 0:
            return None
        return [float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())]
    data = getattr(result.masks, "data", None)
    if data is None or len(data) == 0:
        return None
    mask = data[0].cpu().numpy() > 0.5
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]


def sam_click_box(image_path: str | Path, x_norm: float, y_norm: float, cls_id: int = 0) -> dict:
    path = Path(image_path)
    with Image.open(path) as img:
        width, height = img.size
    px = max(0.0, min(width - 1.0, x_norm * width))
    py = max(0.0, min(height - 1.0, y_norm * height))
    result = get_sam().predict(
        source=str(path),
        points=[[px, py]],
        labels=[1],
        verbose=False,
    )[0]
    xyxy = _mask_xyxy(result)
    if xyxy is None:
        raise RuntimeError("SAM 未生成有效区域，请换一个点再试")
    box = _xyxy_to_yolo(*xyxy, width, height)
    box["cls"] = int(cls_id)
    return box


def map_pred_class(pred_name: str, pred_id: int, class_names: list[str]) -> int | None:
    lookup = {name.lower(): i for i, name in enumerate(class_names)}
    mapped = lookup.get(str(pred_name).lower())
    if mapped is not None:
        return mapped
    if 0 <= pred_id < len(class_names):
        return pred_id
    return None


def yolo_prelabel(weight: str, image_path: str | Path, class_names: list[str], conf: float = 0.25) -> list[dict]:
    result = get_yolo(weight).predict(source=str(image_path), conf=conf, verbose=False)[0]
    height, width = result.orig_shape[:2]
    names = result.names or {}
    boxes = []
    if result.boxes is None:
        return boxes
    for box in result.boxes:
        xyxy = box.xyxy[0].tolist()
        pred_id = int(box.cls[0])
        pred_name = names.get(pred_id, str(pred_id))
        mapped = map_pred_class(pred_name, pred_id, class_names)
        if mapped is None:
            continue
        item = _xyxy_to_yolo(*xyxy, width, height)
        item["cls"] = mapped
        item["conf"] = round(float(box.conf[0]), 4)
        boxes.append(item)
    return boxes

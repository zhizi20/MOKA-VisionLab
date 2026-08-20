"""Ultralytics 检测权重目录。登记后从 GitHub Assets 下载到本地。"""

BUILTIN_YOLO = [
    {"value": "yolo26n.pt", "label": "YOLO26n", "family": "YOLO26", "hint": "最新，最快 / 推荐 CPU"},
    {"value": "yolo26s.pt", "label": "YOLO26s", "family": "YOLO26", "hint": ""},
    {"value": "yolo26m.pt", "label": "YOLO26m", "family": "YOLO26", "hint": ""},
    {"value": "yolo26l.pt", "label": "YOLO26l", "family": "YOLO26", "hint": ""},
    {"value": "yolo26x.pt", "label": "YOLO26x", "family": "YOLO26", "hint": "最大最准"},
    {"value": "yolo11n.pt", "label": "YOLO11n", "family": "YOLO11", "hint": "最快，推荐 CPU"},
    {"value": "yolo11s.pt", "label": "YOLO11s", "family": "YOLO11", "hint": ""},
    {"value": "yolo11m.pt", "label": "YOLO11m", "family": "YOLO11", "hint": ""},
    {"value": "yolo11l.pt", "label": "YOLO11l", "family": "YOLO11", "hint": ""},
    {"value": "yolo11x.pt", "label": "YOLO11x", "family": "YOLO11", "hint": "最大最准"},
    {"value": "yolo12n.pt", "label": "YOLO12n", "family": "YOLO12", "hint": "最快，推荐 CPU"},
    {"value": "yolo12s.pt", "label": "YOLO12s", "family": "YOLO12", "hint": ""},
    {"value": "yolo12m.pt", "label": "YOLO12m", "family": "YOLO12", "hint": ""},
    {"value": "yolo12l.pt", "label": "YOLO12l", "family": "YOLO12", "hint": ""},
    {"value": "yolo12x.pt", "label": "YOLO12x", "family": "YOLO12", "hint": "最大最准"},
    {"value": "yolov8n.pt", "label": "YOLOv8n", "family": "YOLOv8", "hint": "最快，推荐 CPU"},
    {"value": "yolov8s.pt", "label": "YOLOv8s", "family": "YOLOv8", "hint": ""},
    {"value": "yolov8m.pt", "label": "YOLOv8m", "family": "YOLOv8", "hint": ""},
    {"value": "yolov8l.pt", "label": "YOLOv8l", "family": "YOLOv8", "hint": ""},
    {"value": "yolov8x.pt", "label": "YOLOv8x", "family": "YOLOv8", "hint": "最大最准"},
]


def builtin_label(value: str) -> str:
    for item in BUILTIN_YOLO:
        if item["value"] == value:
            hint = f"（{item['hint']}）" if item.get("hint") else ""
            return f"{item['label']}{hint}"
    return value

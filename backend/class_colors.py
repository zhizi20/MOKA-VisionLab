"""类别框颜色：标注与检测共用。"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_COLORS = [
    "#ff2d95", "#00e5ff", "#ffd400", "#7cff6b", "#ff8a00",
    "#c084fc", "#22d3ee", "#fb7185", "#60a5fa", "#a3e635",
]

COLORS_FILE = "colors.json"


def hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return (0, 213, 255)
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


def palette_for(class_names: list[str], saved: list[str] | None = None) -> list[str]:
    colors = []
    for i, _name in enumerate(class_names):
        if saved and i < len(saved) and saved[i]:
            colors.append(saved[i])
        else:
            colors.append(DEFAULT_COLORS[i % len(DEFAULT_COLORS)])
    return colors


def load_dataset_colors(ds_dir: Path, class_names: list[str]) -> list[str]:
    path = ds_dir / COLORS_FILE
    saved = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                saved = [str(x) for x in data]
        except json.JSONDecodeError:
            saved = []
    return palette_for(class_names, saved)


def save_dataset_colors(ds_dir: Path, colors: list[str]):
    ds_dir.mkdir(parents=True, exist_ok=True)
    (ds_dir / COLORS_FILE).write_text(json.dumps(colors, ensure_ascii=False), encoding="utf-8")


def name_color_map(class_names: list[str], colors: list[str]) -> dict[str, str]:
    return {name: colors[i] if i < len(colors) else DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
            for i, name in enumerate(class_names)}


GLOBAL_FILE = "class_colors.json"


def load_global_colors(upload_folder: Path) -> dict[str, str]:
    path = Path(upload_folder) / GLOBAL_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if v}
    except json.JSONDecodeError:
        return {}
    return {}


def save_global_colors(upload_folder: Path, mapping: dict[str, str]):
    path = Path(upload_folder) / GLOBAL_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")


def update_global_colors(upload_folder: Path, class_names: list[str], colors: list[str]):
    mapping = load_global_colors(upload_folder)
    mapping.update(name_color_map(class_names, colors))
    save_global_colors(upload_folder, mapping)
    return mapping

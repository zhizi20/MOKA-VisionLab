"""把数据集打成 ZIP，方便发给别人；对方用「导入 ZIP」还原。"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

PACK_FORMAT = "moka-visionlab-dataset"
PACK_VERSION = 1
MANIFEST = "manifest.json"
README_NAME = "README.txt"
SKIP_FILES = {"source.ndjson", "failed.json"}

README_TEXT = """这是 MOKA-VisionLab 导出的数据集包。

在本软件「数据集」页点「导入 ZIP」，选这个文件即可还原图片和标注。

也可以当普通 YOLO 数据用：
- 已构建过：解压后看 yolo/images 与 yolo/labels
- 未构建：看 raw/images 与 raw/labels（YOLO txt 标注）
"""


def _skip(rel: Path) -> bool:
    if rel.name in SKIP_FILES or rel.name == README_NAME:
        return True
    if any(part.startswith(".") for part in rel.parts):
        return True
    return False


def write_dataset_zip(ds_dir: Path, zip_path: Path, meta: dict) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": PACK_FORMAT,
        "version": PACK_VERSION,
        **meta,
    }
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST, json.dumps(payload, ensure_ascii=False, indent=2))
        zf.writestr(README_NAME, README_TEXT)
        if not ds_dir.exists():
            return
        for path in ds_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(ds_dir)
            if _skip(rel):
                continue
            zf.write(path, rel.as_posix())


def _safe_members(zf: zipfile.ZipFile, dest: Path):
    dest = dest.resolve()
    for info in zf.infolist():
        name = Path(info.filename)
        if info.is_dir() or name.is_absolute() or ".." in name.parts:
            continue
        target = (dest / name).resolve()
        try:
            target.relative_to(dest)
        except ValueError:
            continue
        yield info, target


def extract_zip(zip_path: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for info, target in _safe_members(zf, dest):
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
    return find_pack_root(dest)


def find_pack_root(extracted: Path) -> Path:
    if (extracted / MANIFEST).is_file() or (extracted / "raw" / "images").is_dir():
        return extracted
    dirs = [p for p in extracted.iterdir() if p.is_dir()]
    if len(dirs) == 1:
        child = dirs[0]
        if (child / MANIFEST).is_file() or (child / "raw" / "images").is_dir():
            return child
    for path in extracted.rglob(MANIFEST):
        return path.parent
    for path in extracted.rglob("images"):
        if path.parent.name == "raw" and path.is_dir():
            return path.parent.parent
    raise RuntimeError("不是本软件导出的数据集包（缺少 raw/images 或 manifest.json）")


def read_manifest(root: Path) -> dict:
    path = root / MANIFEST
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"数据包说明损坏：{exc}") from exc
    if not isinstance(data, dict):
        return {}
    return data

"""把数据集打成 ZIP，方便发给别人；对方用「导入 ZIP」还原。"""
from __future__ import annotations

import json
import shutil
import threading
import zipfile
from pathlib import Path

PACK_FORMAT = "moka-visionlab-dataset"
PACK_VERSION = 1
MANIFEST = "manifest.json"
README_NAME = "README.txt"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
EXPORT_MODES = ("labeled", "unlabeled", "all")
MODE_FILE_SUFFIX = {"labeled": "labeled", "unlabeled": "unlabeled", "all": "raw"}

export_jobs: dict[str, dict] = {}
export_jobs_lock = threading.Lock()
latest_export_jobs: dict[int, str] = {}

README_TEXT = """这是 MOKA-VisionLab 导出的数据集包。

在本软件「数据集」页点「导入 ZIP」，选这个文件即可还原。

包里只有 raw（按导出选项：已标注 / 未标注 / 全部），不含「构建」后的 train/val 副本，避免同一张图打两份。
导入后若要训练，再点「构建」划分即可。
"""


def normalize_mode(mode: str | None) -> str:
    raw = (mode or "labeled").strip().lower()
    aliases = {
        "annotated": "labeled",
        "labelled": "labeled",
        "done": "labeled",
        "raw": "unlabeled",
        "unlabelled": "unlabeled",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in EXPORT_MODES else "labeled"


def empty_export_message(mode: str) -> str:
    mode = normalize_mode(mode)
    if mode == "labeled":
        return "没有已标注的图片，先去标注再导出"
    if mode == "unlabeled":
        return "没有未标注的图片"
    return "这个数据集还没有图片，先上传或标注再导出"


def export_suffix(mode: str) -> str:
    return MODE_FILE_SUFFIX[normalize_mode(mode)]


def _has_label(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def pack_items(ds_dir: Path, mode: str = "labeled") -> list[tuple[Path, str]]:
    """只从 raw 取材，不打包 yolo/ 划分副本。"""
    mode = normalize_mode(mode)
    items: list[tuple[Path, str]] = []
    colors = ds_dir / "colors.json"
    if colors.is_file():
        items.append((colors, "colors.json"))
    img_dir = ds_dir / "raw" / "images"
    lbl_dir = ds_dir / "raw" / "labels"
    if not img_dir.is_dir():
        return items
    for path in sorted(img_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXT:
            continue
        labeled = _has_label(lbl_dir / f"{path.stem}.txt")
        if mode == "labeled" and not labeled:
            continue
        if mode == "unlabeled" and labeled:
            continue
        items.append((path, f"raw/images/{path.name}"))
        if labeled:
            lbl = lbl_dir / f"{path.stem}.txt"
            items.append((lbl, f"raw/labels/{lbl.name}"))
    return items


def pack_image_count(items: list[tuple[Path, str]]) -> int:
    return sum(1 for _, arc in items if arc.startswith("raw/images/"))


def bind_export_job(dataset_id: int, job_id: str):
    latest_export_jobs[dataset_id] = job_id


def snapshot_export(dataset_id: int) -> dict | None:
    jid = latest_export_jobs.get(dataset_id)
    if not jid:
        return None
    with export_jobs_lock:
        job = export_jobs.get(jid)
        if not job:
            return None
        if job.get("status") not in {"running", "ready"}:
            return None
        return {
            "jobId": jid,
            "status": job.get("status"),
            "stage": job.get("stage") or "packing",
            "progress": int(job.get("progress") or 0),
            "processed": int(job.get("processed") or 0),
            "total": int(job.get("total") or 0),
            "filename": job.get("filename") or "",
        }


def write_dataset_zip(ds_dir: Path, zip_path: Path, meta: dict, on_progress=None, mode: str = "labeled") -> None:
    mode = normalize_mode(mode)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    items = pack_items(ds_dir, mode)
    payload = {
        "format": PACK_FORMAT,
        "version": PACK_VERSION,
        "exportMode": mode,
        **meta,
    }
    total = max(len(items), 1)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST, json.dumps(payload, ensure_ascii=False, indent=2))
        zf.writestr(README_NAME, README_TEXT)
        if not items:
            if on_progress:
                on_progress(1, 1)
            return
        for index, (path, arcname) in enumerate(items, 1):
            zf.write(path, arcname)
            if on_progress:
                on_progress(index, total)


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

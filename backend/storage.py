"""uploads 目录布局：按可读名称存放，而不是 1、job_1。"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from sqlalchemy import inspect, text

from config import Config
from extensions import db
from models import Dataset, DetectModel, TrainJob

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def slugify(name: str, fallback: str = "item") -> str:
    text = _ILLEGAL.sub("", (name or "").strip())
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip(" .-_")
    if not text:
        text = fallback
    if text.upper() in _WINDOWS_RESERVED:
        text = f"_{text}"
    return text[:80]


def unique_folder(parent: Path, base: str, rec_id: int, reserved: set[str], allow: Path | None = None) -> str:
    parent.mkdir(parents=True, exist_ok=True)
    dest = parent / base
    same = allow is not None and dest.exists() and dest.resolve() == allow.resolve()
    if base not in reserved and (not dest.exists() or same):
        return base
    name = f"{base}_{rec_id}"
    n = 2
    while name in reserved or (parent / name).exists():
        name = f"{base}_{rec_id}_{n}"
        n += 1
    return name


def dataset_dir(ds: Dataset) -> Path:
    if ds.folder:
        named = Config.DATASET_FOLDER / ds.folder
        if named.exists() or not (Config.DATASET_FOLDER / str(ds.id)).exists():
            return named
    legacy = Config.DATASET_FOLDER / str(ds.id)
    if legacy.exists():
        return legacy
    return Config.DATASET_FOLDER / (ds.folder or slugify(ds.name, f"dataset-{ds.id}"))


def training_dir(job: TrainJob) -> Path:
    if job.folder:
        named = Config.TRAINING_FOLDER / job.folder
        if named.exists() or not (Config.TRAINING_FOLDER / f"job_{job.id}").exists():
            return named
    legacy = Config.TRAINING_FOLDER / f"job_{job.id}"
    if legacy.exists():
        return legacy
    return Config.TRAINING_FOLDER / (job.folder or slugify(job.job_name, f"train-{job.id}"))


def training_exp_dir(job: TrainJob) -> Path:
    return training_dir(job) / "exp"


def builtin_weight_path(filename: str) -> Path:
    return Config.MODEL_FOLDER / "builtin" / Path(filename).name


def custom_model_dir(model_key: str) -> Path:
    return Config.MODEL_FOLDER / "custom" / model_key


def trained_model_dir(folder: str) -> Path:
    return Config.MODEL_FOLDER / "trained" / folder


def rewrite_data_yaml(ds_dir: Path) -> None:
    yaml_path = ds_dir / "yolo" / "data.yaml"
    if not yaml_path.exists():
        return
    yolo = (ds_dir / "yolo").as_posix()
    lines = []
    for line in yaml_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("path:"):
            lines.append(f"path: {yolo}")
        else:
            lines.append(line)
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _safe_move(src: Path, dest: Path) -> Path:
    if src.resolve() == dest.resolve():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    shutil.move(str(src), str(dest))
    return dest


def _add_column(table: str, name: str, ddl: str) -> None:
    cols = {c["name"] for c in inspect(db.engine).get_columns(table)}
    if name in cols:
        return
    db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
    db.session.commit()


def ensure_schema() -> None:
    _add_column("dataset", "folder", "folder VARCHAR(160) DEFAULT ''")
    _add_column("train_job", "folder", "folder VARCHAR(160) DEFAULT ''")


def assign_dataset_folder(ds: Dataset, rename: bool = False) -> Path:
    reserved = {
        (other.folder or "")
        for other in Dataset.query.filter(Dataset.id != ds.id).all()
        if other.folder
    }
    base = slugify(ds.name, f"dataset-{ds.id}")
    current = dataset_dir(ds)
    dest_name = unique_folder(Config.DATASET_FOLDER, base, ds.id, reserved, allow=current if current.exists() else None)
    if ds.folder and not rename and (Config.DATASET_FOLDER / ds.folder).exists():
        return Config.DATASET_FOLDER / ds.folder
    dest = Config.DATASET_FOLDER / dest_name
    if current.exists() and current.resolve() != dest.resolve():
        _safe_move(current, dest)
    else:
        dest.mkdir(parents=True, exist_ok=True)
    rewrite_data_yaml(dest)
    ds.folder = dest_name
    return dest


def assign_train_folder(job: TrainJob, rename: bool = False) -> Path:
    reserved = {
        (other.folder or "")
        for other in TrainJob.query.filter(TrainJob.id != job.id).all()
        if other.folder
    }
    base = slugify(job.job_name, f"train-{job.id}")
    current = training_dir(job)
    dest_name = unique_folder(Config.TRAINING_FOLDER, base, job.id, reserved, allow=current if current.exists() else None)
    if job.folder and not rename and (Config.TRAINING_FOLDER / job.folder).exists():
        return Config.TRAINING_FOLDER / job.folder
    dest = Config.TRAINING_FOLDER / dest_name
    if current.exists() and current.resolve() != dest.resolve():
        _safe_move(current, dest)
    else:
        dest.mkdir(parents=True, exist_ok=True)
    job.folder = dest_name
    return dest


def _migrate_loose_files() -> None:
    ds_root = Config.DATASET_FOLDER
    tmp = Config.TMP_FOLDER
    tmp.mkdir(parents=True, exist_ok=True)
    if ds_root.exists():
        for path in list(ds_root.iterdir()):
            if path.is_file() and (path.name.startswith("import_") or path.name.startswith("_tmp_")):
                _safe_move(path, tmp / path.name)

    legacy_out = Config.UPLOAD_FOLDER / "outputs"
    Config.OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    if legacy_out.exists() and legacy_out.resolve() != Config.OUTPUT_FOLDER.resolve():
        for path in list(legacy_out.iterdir()):
            _safe_move(path, Config.OUTPUT_FOLDER / path.name)
        try:
            legacy_out.rmdir()
        except OSError:
            pass

    videos = Config.UPLOAD_FOLDER / "videos"
    Config.VIDEO_FOLDER.mkdir(parents=True, exist_ok=True)
    if videos.exists():
        for path in list(videos.iterdir()):
            if path.name in {"source", "results"}:
                continue
            if path.is_file():
                _safe_move(path, Config.VIDEO_FOLDER / path.name)


def _migrate_models() -> None:
    builtin = Config.MODEL_FOLDER / "builtin"
    custom = Config.MODEL_FOLDER / "custom"
    trained = Config.MODEL_FOLDER / "trained"
    builtin.mkdir(parents=True, exist_ok=True)
    custom.mkdir(parents=True, exist_ok=True)
    trained.mkdir(parents=True, exist_ok=True)
    for m in DetectModel.query.all():
        if not m.file_path:
            continue
        src = Path(m.file_path)
        if not src.exists():
            continue
        if m.source == "builtin":
            dest = builtin / src.name
        elif m.source == "train":
            folder = slugify(m.name.replace("-best", ""), m.model_key)
            dest = trained / folder / "best.pt"
        else:
            dest = custom / m.model_key / src.name
        if src.resolve() != dest.resolve():
            _safe_move(src, dest)
            parent = src.parent
            if parent.exists() and parent != Config.MODEL_FOLDER and not any(parent.iterdir()):
                shutil.rmtree(parent, ignore_errors=True)
        m.file_path = str(dest)
        m.file_size = dest.stat().st_size if dest.exists() else m.file_size
    db.session.commit()


def migrate_uploads() -> None:
    Config.DATASET_FOLDER.mkdir(parents=True, exist_ok=True)
    Config.TRAINING_FOLDER.mkdir(parents=True, exist_ok=True)
    _migrate_loose_files()
    for ds in Dataset.query.order_by(Dataset.id.asc()).all():
        assign_dataset_folder(ds, rename=not bool(ds.folder))
    for job in TrainJob.query.order_by(TrainJob.id.asc()).all():
        assign_train_folder(job, rename=not bool(job.folder))
    _migrate_models()
    _cleanup_empty_legacy_dirs()
    db.session.commit()


def _is_empty_tree(path: Path) -> bool:
    if not path.exists():
        return True
    return not any(p.is_file() for p in path.rglob("*"))


def _cleanup_empty_legacy_dirs() -> None:
    for ds in Dataset.query.all():
        if not ds.folder:
            continue
        named = Config.DATASET_FOLDER / ds.folder
        legacy = Config.DATASET_FOLDER / str(ds.id)
        if named.exists() and legacy.exists() and named.resolve() != legacy.resolve() and _is_empty_tree(legacy):
            shutil.rmtree(legacy, ignore_errors=True)
    for job in TrainJob.query.all():
        if not job.folder:
            continue
        named = Config.TRAINING_FOLDER / job.folder
        legacy = Config.TRAINING_FOLDER / f"job_{job.id}"
        if named.exists() and legacy.exists() and named.resolve() != legacy.resolve() and _is_empty_tree(legacy):
            shutil.rmtree(legacy, ignore_errors=True)
    for leftover in ("yolo11n", "yolo26n", "yolo12n"):
        path = Config.MODEL_FOLDER / leftover
        if path.is_dir() and _is_empty_tree(path):
            shutil.rmtree(path, ignore_errors=True)

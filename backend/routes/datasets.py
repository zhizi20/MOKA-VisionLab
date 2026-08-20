import os
import random
import shutil
import threading
import uuid
from pathlib import Path

import cv2
from flask import Blueprint, after_this_request, current_app, request, send_file

from class_colors import (
    load_dataset_colors,
    load_global_colors,
    palette_for,
    save_dataset_colors,
    update_global_colors,
)
from config import Config
from extensions import db
from models import Dataset, DetectModel
from ndjson_import import (
    SOURCE_FILE,
    bind_dataset_job,
    class_name_list,
    dedupe_images,
    find_source_ndjson,
    import_jobs,
    import_jobs_lock,
    latest_dataset_jobs,
    list_missing,
    missing_failures,
    parse_ndjson,
    run_ndjson_import,
    set_paused,
    snapshot_job,
)
from routes.models import resolve_weight
from security import login_required
from smart_label import sam_click_box, yolo_prelabel
from dataset_pack import extract_zip, read_manifest, write_dataset_zip
from storage import assign_dataset_folder, dataset_dir, rewrite_data_yaml, slugify
from utils import fail, ok

datasets_bp = Blueprint("datasets", __name__, url_prefix="/api/datasets")


def _ds_dir(ds: Dataset) -> Path:
    return dataset_dir(ds)


def _raw_images(ds: Dataset) -> Path:
    p = _ds_dir(ds) / "raw" / "images"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _raw_labels(ds: Dataset) -> Path:
    p = _ds_dir(ds) / "raw" / "labels"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _classes(ds: Dataset) -> list[str]:
    return [c.strip() for c in (ds.class_names or "").split(",") if c.strip()]


def _image_stats(ds: Dataset) -> tuple[int, int]:
    img_dir = _ds_dir(ds) / "raw" / "images"
    lbl_dir = _ds_dir(ds) / "raw" / "labels"
    if not img_dir.exists():
        return 0, 0
    n = 0
    labeled = 0
    for p in img_dir.iterdir():
        if p.suffix.lower() not in Config.IMAGE_ALLOWED_EXT:
            continue
        n += 1
        lbl = lbl_dir / f"{p.stem}.txt"
        if lbl.exists() and lbl.read_text(encoding="utf-8").strip():
            labeled += 1
    return n, labeled


def _label_class_ids(path: Path) -> list[int]:
    ids: set[int] = set()
    if not path.exists():
        return []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts:
            continue
        try:
            ids.add(int(float(parts[0])))
        except ValueError:
            continue
    return sorted(ids)


def _to_dict(ds: Dataset) -> dict:
    ds_dir = _ds_dir(ds)
    has_import = (ds_dir / SOURCE_FILE).is_file()
    failed = missing_failures(ds_dir) if has_import else []
    names = _classes(ds)
    image_count, labeled_count = _image_stats(ds)
    colors = load_dataset_colors(ds_dir, names) if names else []
    return {
        "id": ds.id,
        "name": ds.name,
        "classNames": names,
        "colors": colors,
        "status": ds.status,
        "imageCount": image_count,
        "labeledCount": labeled_count,
        "trainCount": ds.train_count,
        "valCount": ds.val_count,
        "built": ds.status == "ready",
        "splitRatio": ds.split_ratio,
        "description": ds.description,
        "folder": ds.folder or "",
        "hasImport": has_import,
        "failedCount": len(failed),
        "failures": failed[:50],
        "folderPath": str(_raw_images(ds)),
        "importJob": snapshot_job(ds.id),
        "createTime": ds.create_time.strftime("%Y-%m-%d %H:%M:%S") if ds.create_time else "",
    }


def _find_image(ds: Dataset, stem: str) -> Path | None:
    for ext in Config.IMAGE_ALLOWED_EXT:
        p = _raw_images(ds) / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def _read_boxes(path: Path) -> list[dict]:
    boxes = []
    if not path.exists():
        return boxes
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 5:
            boxes.append({
                "cls": int(float(parts[0])),
                "cx": float(parts[1]),
                "cy": float(parts[2]),
                "w": float(parts[3]),
                "h": float(parts[4]),
            })
    return boxes


def _write_boxes(path: Path, boxes: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for b in boxes:
        lines.append(f"{int(b['cls'])} {b['cx']:.6f} {b['cy']:.6f} {b['w']:.6f} {b['h']:.6f}")
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _sync_yolo_labels(ds: Dataset, stem: str, boxes: list[dict]):
    """标注改的是 raw；若 yolo 划分里已有同名图，同步过去，避免看起来没保存。"""
    yolo = _ds_dir(ds) / "yolo"
    for split in ("train", "val", "test"):
        img_dir = yolo / "images" / split
        if not img_dir.exists():
            continue
        has_img = any(img_dir.glob(f"{stem}.*"))
        lbl = yolo / "labels" / split / f"{stem}.txt"
        if has_img or lbl.exists():
            _write_boxes(lbl, boxes)


@datasets_bp.get("")
@login_required
def list_datasets():
    rows = [_to_dict(d) for d in Dataset.query.order_by(Dataset.id.desc()).all()]
    return ok({"rows": rows, "total": len(rows)})


@datasets_bp.post("/import-ndjson")
@login_required
def import_ndjson():
    """导入 Ultralytics Platform 导出的 .ndjson，后台按 URL 下载图片与标注。"""
    f = request.files.get("file")
    local_path = (request.form.get("localPath") or "").strip()
    src = None
    tmp = None
    if f and f.filename:
        if not f.filename.lower().endswith(".ndjson"):
            return fail("请选择 .ndjson 文件")
        Config.TMP_FOLDER.mkdir(parents=True, exist_ok=True)
        tmp = Config.TMP_FOLDER / f"_tmp_{uuid.uuid4().hex}.ndjson"
        f.save(tmp)
        src = tmp
    elif local_path:
        src = Path(local_path)
        if not src.is_file():
            return fail("本机路径不存在")
    else:
        return fail("请上传 .ndjson 或填写本机路径")
    try:
        meta, images = parse_ndjson(src)
    except Exception as exc:  # noqa: BLE001
        if tmp:
            tmp.unlink(missing_ok=True)
        return fail(f"解析 NDJSON 失败：{exc}")
    images = dedupe_images(images)
    if not images:
        if tmp:
            tmp.unlink(missing_ok=True)
        return fail("NDJSON 中没有图片记录")
    names = class_name_list(meta)
    if not names:
        if tmp:
            tmp.unlink(missing_ok=True)
        return fail("NDJSON 中没有类别")
    ds = Dataset(
        name=(meta.get("name") or src.stem).strip(),
        class_names=",".join(names),
        description=meta.get("description") or "从 Ultralytics NDJSON 导入",
        status="importing",
        split_ratio=0.8,
    )
    db.session.add(ds)
    db.session.commit()
    assign_dataset_folder(ds)
    db.session.commit()
    ds_dir = _ds_dir(ds)
    ds_dir.mkdir(parents=True, exist_ok=True)
    stored = ds_dir / SOURCE_FILE
    if src.resolve() != stored.resolve():
        shutil.copy2(src, stored)
    if tmp:
        tmp.unlink(missing_ok=True)
    save_dataset_colors(ds_dir, palette_for(names))
    update_global_colors(Config.UPLOAD_FOLDER, names, palette_for(names))
    job_id = uuid.uuid4().hex
    with import_jobs_lock:
        import_jobs[job_id] = {
            "status": "running",
            "datasetId": ds.id,
            "paused": False,
            "total": len(images),
            "processed": 0,
            "failed": 0,
            "progress": 0,
            "failures": [],
            "error": None,
        }
    bind_dataset_job(ds.id, job_id)
    app = current_app._get_current_object()
    threading.Thread(
        target=_run_import,
        args=(app, job_id, ds.id, names, images),
        daemon=True,
    ).start()
    return ok({"jobId": job_id, "datasetId": ds.id, "total": len(images)}, "已开始下载图片")


@datasets_bp.get("/import-progress/<job_id>")
@login_required
def import_progress(job_id: str):
    with import_jobs_lock:
        job = import_jobs.get(job_id)
    if job is None:
        return fail("导入任务不存在", 404)
    return ok(job)


@datasets_bp.post("/<int:did>/import-pause")
@login_required
def pause_import(did: int):
    job = snapshot_job(did)
    if job is None:
        return fail("该数据集当前没有进行中的下载任务")
    if not set_paused(job["jobId"], True):
        return fail("无法暂停")
    return ok(snapshot_job(did), "已暂停下载")


@datasets_bp.post("/<int:did>/import-resume")
@login_required
def resume_import(did: int):
    jid = latest_dataset_jobs.get(did)
    if not jid:
        return fail("该数据集当前没有可继续的下载任务")
    if not set_paused(jid, False):
        return fail("无法继续")
    return ok(snapshot_job(did), "已继续下载")


@datasets_bp.get("/class-colors")
@login_required
def global_class_colors():
    return ok(load_global_colors(Config.UPLOAD_FOLDER))


@datasets_bp.get("/<int:did>/colors")
@login_required
def get_colors(did: int):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    names = _classes(ds)
    colors = load_dataset_colors(_ds_dir(ds), names)
    return ok({"classNames": names, "colors": colors})


@datasets_bp.put("/<int:did>/colors")
@login_required
def put_colors(did: int):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    names = _classes(ds)
    data = request.get_json(silent=True) or {}
    colors = palette_for(names, data.get("colors") or [])
    save_dataset_colors(_ds_dir(ds), colors)
    update_global_colors(Config.UPLOAD_FOLDER, names, colors)
    return ok({"classNames": names, "colors": colors}, "已保存颜色")


@datasets_bp.post("/<int:did>/open-folder")
@login_required
def open_folder(did: int):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    path = _raw_images(ds)
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])  # noqa: S603
    except OSError as exc:
        return fail(f"无法打开目录：{exc}")
    return ok({"path": str(path)}, "已打开资源管理器")


def _apply_import_stats(ds: Dataset, stats: dict):
    ds.train_count = stats["train"]
    ds.val_count = stats["val"]
    if stats.get("complete") and stats["train"] and stats["val"]:
        ds.status = "ready"
    elif stats.get("failed"):
        ds.status = "incomplete"
    elif stats["train"] and stats["val"]:
        ds.status = "ready"
    else:
        ds.status = "raw"


def _run_import(app, job_id: str, ds_id: int, names: list[str], images: list[dict]):
    with app.app_context():
        try:
            ds = db.session.get(Dataset, ds_id)
            stats = run_ndjson_import(job_id, _ds_dir(ds), names, images)
            ds = db.session.get(Dataset, ds_id)
            _apply_import_stats(ds, stats)
            db.session.commit()
            with import_jobs_lock:
                job = import_jobs.get(job_id)
                if job:
                    job["status"] = "done"
                    job["ready"] = stats["ready"]
                    job["complete"] = stats["complete"]
                    job["trainCount"] = stats["train"]
                    job["valCount"] = stats["val"]
                    job["failed"] = stats["failed"]
                    job["failures"] = stats.get("failures") or []
                    job["processed"] = stats.get("ok") or 0
        except Exception as exc:  # noqa: BLE001
            ds = db.session.get(Dataset, ds_id)
            if ds:
                ds.status = "raw"
                db.session.commit()
            with import_jobs_lock:
                job = import_jobs.get(job_id)
                if job:
                    job.update(status="failed", error=str(exc))


@datasets_bp.post("/<int:did>/retry-import")
@login_required
def retry_import(did: int):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    ds_dir = _ds_dir(ds)
    upload = request.files.get("file")
    stored = ds_dir / SOURCE_FILE
    if upload and upload.filename:
        if not str(upload.filename).lower().endswith(".ndjson"):
            return fail("请选择该数据集对应的 .ndjson 文件")
        ds_dir.mkdir(parents=True, exist_ok=True)
        upload.save(stored)
    src = find_source_ndjson(ds_dir)
    if src is None or not src.is_file():
        return fail("该数据集没有绑定的 NDJSON，无法重试。请对该数据集重新导入，不要用其它数据集的索引。")
    try:
        meta, images = parse_ndjson(src)
    except Exception as exc:  # noqa: BLE001
        return fail(f"解析 NDJSON 失败：{exc}")
    meta_name = (meta.get("name") or "").strip()
    if meta_name and meta_name.lower() != (ds.name or "").strip().lower():
        return fail(
            f"该数据集绑定的 NDJSON 属于「{meta_name}」，与当前数据集「{ds.name}」不一致。"
            "请删除该数据集后重新导入，不要重试。"
        )
    images = dedupe_images(images)
    names = _classes(ds) or class_name_list(meta)
    missing = list_missing(ds_dir, images)
    if not missing:
        ds.status = "ready" if (ds.train_count and ds.val_count) else ds.status
        db.session.commit()
        return ok({"missing": 0}, "没有缺失图片")
    ds.status = "importing"
    db.session.commit()
    job_id = uuid.uuid4().hex
    with import_jobs_lock:
        import_jobs[job_id] = {
            "status": "running",
            "datasetId": ds.id,
            "paused": False,
            "total": len(images),
            "processed": len(images) - len(missing),
            "failed": 0,
            "progress": 0,
            "failures": [],
            "error": None,
        }
    bind_dataset_job(ds.id, job_id)
    app = current_app._get_current_object()
    threading.Thread(
        target=_run_import,
        args=(app, job_id, ds.id, names, images),
        daemon=True,
    ).start()
    return ok(
        {"jobId": job_id, "datasetId": ds.id, "missing": len(missing), "total": len(images)},
        f"开始补下 {len(missing)} 张失败图片",
    )


@datasets_bp.get("/<int:did>/export")
@login_required
def export_dataset(did: int):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    img_dir = _raw_images(ds)
    if not img_dir.exists() or not any(img_dir.iterdir()):
        return fail("这个数据集还没有图片，先上传或标注再导出")
    names = _classes(ds)
    Config.TMP_FOLDER.mkdir(parents=True, exist_ok=True)
    zip_path = Config.TMP_FOLDER / f"export_{ds.id}_{uuid.uuid4().hex}.zip"
    write_dataset_zip(
        _ds_dir(ds),
        zip_path,
        {
            "name": ds.name,
            "classNames": names,
            "splitRatio": ds.split_ratio,
            "description": ds.description or "",
            "status": ds.status,
            "trainCount": ds.train_count,
            "valCount": ds.val_count,
        },
    )

    @after_this_request
    def _cleanup(response):
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass
        return response

    filename = f"{slugify(ds.name, 'dataset')}.zip"
    return send_file(zip_path, as_attachment=True, download_name=filename, mimetype="application/zip")


@datasets_bp.post("/import-zip")
@login_required
def import_zip():
    f = request.files.get("file")
    if f is None or not f.filename:
        return fail("请选择导出的 .zip 数据包")
    if not f.filename.lower().endswith(".zip"):
        return fail("请选择 .zip 文件")
    Config.TMP_FOLDER.mkdir(parents=True, exist_ok=True)
    tmp_zip = Config.TMP_FOLDER / f"_import_{uuid.uuid4().hex}.zip"
    tmp_dir = Config.TMP_FOLDER / f"_unpack_{uuid.uuid4().hex}"
    f.save(tmp_zip)
    try:
        root = extract_zip(tmp_zip, tmp_dir)
        meta = read_manifest(root)
        raw_images = root / "raw" / "images"
        if not raw_images.is_dir() or not any(raw_images.iterdir()):
            return fail("数据包里没有图片（raw/images 为空）")
        names = meta.get("classNames") or []
        if isinstance(names, str):
            names = [x.strip() for x in names.split(",") if x.strip()]
        names = [str(x).strip() for x in names if str(x).strip()]
        if not names:
            names = _classes_from_labels(root / "raw" / "labels") or ["object"]
        name = (meta.get("name") or Path(f.filename).stem or "imported").strip()
        ds = Dataset(
            name=name,
            class_names=",".join(names),
            split_ratio=float(meta.get("splitRatio") or 0.8),
            description=meta.get("description") or "从 ZIP 数据包导入",
            status="raw",
        )
        db.session.add(ds)
        db.session.commit()
        dest = assign_dataset_folder(ds)
        db.session.commit()
        _copy_pack_into(root, dest)
        rewrite_data_yaml(dest)
        names = _classes(ds)
        colors = load_dataset_colors(dest, names)
        save_dataset_colors(dest, colors)
        update_global_colors(Config.UPLOAD_FOLDER, names, colors)
        image_count, labeled_count = _image_stats(ds)
        yolo_ok = (dest / "yolo" / "images" / "train").exists() and (dest / "yolo" / "images" / "val").exists()
        if yolo_ok:
            train_n = len([p for p in (dest / "yolo" / "images" / "train").iterdir() if p.is_file()])
            val_n = len([p for p in (dest / "yolo" / "images" / "val").iterdir() if p.is_file()])
            ds.train_count = train_n
            ds.val_count = val_n
            ds.status = "ready" if train_n and val_n else "raw"
        else:
            ds.status = "raw"
        db.session.commit()
        msg = f"已导入 {image_count} 张图"
        if labeled_count:
            msg += f"，其中 {labeled_count} 张已标注"
        if ds.status == "ready":
            msg += "，可直接去训练"
        else:
            msg += "。需要的话再点「构建」"
        return ok(_to_dict(ds), msg)
    except Exception as exc:  # noqa: BLE001
        return fail(f"导入失败：{exc}")
    finally:
        tmp_zip.unlink(missing_ok=True)
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _copy_pack_into(root: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("raw", "yolo", "colors.json"):
        src = root / name
        if src.is_dir():
            target = dest / name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target)
        elif src.is_file():
            shutil.copy2(src, dest / name)


def _classes_from_labels(label_dir: Path) -> list[str]:
    ids: set[int] = set()
    if not label_dir.is_dir():
        return []
    for path in label_dir.glob("*.txt"):
        ids.update(_label_class_ids(path))
    if not ids:
        return []
    return [str(i) for i in range(max(ids) + 1)]


@datasets_bp.post("")
@login_required
def add_dataset():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    names = data.get("classNames") or []
    if not name:
        return fail("请填写数据集名称")
    if not names:
        return fail("请至少填写一个检测类别")
    ds = Dataset(
        name=name,
        class_names=",".join(str(c).strip() for c in names if str(c).strip()),
        split_ratio=float(data.get("splitRatio") or 0.8),
        description=data.get("description") or "",
    )
    db.session.add(ds)
    db.session.commit()
    assign_dataset_folder(ds)
    db.session.commit()
    names = _classes(ds)
    save_dataset_colors(_ds_dir(ds), palette_for(names))
    update_global_colors(Config.UPLOAD_FOLDER, names, palette_for(names))
    _raw_images(ds)
    _raw_labels(ds)
    return ok(_to_dict(ds), "已创建")


@datasets_bp.put("/<int:did>")
@login_required
def update_dataset(did: int):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    data = request.get_json(silent=True) or {}
    old_name = ds.name
    ds.name = (data.get("name") or ds.name).strip()
    if "classNames" in data:
        ds.class_names = ",".join(str(c).strip() for c in (data.get("classNames") or []) if str(c).strip())
        names = _classes(ds)
        colors = load_dataset_colors(_ds_dir(ds), names)
        save_dataset_colors(_ds_dir(ds), colors)
        update_global_colors(Config.UPLOAD_FOLDER, names, colors)
    if "splitRatio" in data:
        ds.split_ratio = float(data.get("splitRatio") or ds.split_ratio)
    if "description" in data:
        ds.description = data.get("description") or ""
    if ds.name != old_name:
        assign_dataset_folder(ds, rename=True)
    db.session.commit()
    return ok(_to_dict(ds))


@datasets_bp.delete("/<int:did>")
@login_required
def remove_dataset(did: int):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    shutil.rmtree(_ds_dir(ds), ignore_errors=True)
    db.session.delete(ds)
    db.session.commit()
    return ok(message="已删除")


@datasets_bp.post("/<int:did>/upload")
@login_required
def upload_images(did: int):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    files = request.files.getlist("files")
    if not files:
        one = request.files.get("file")
        files = [one] if one else []
    img_dir = _raw_images(ds)
    saved = 0
    for f in files:
        if f is None or not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in Config.IMAGE_ALLOWED_EXT:
            continue
        dest = img_dir / Path(f.filename).name
        f.save(dest)
        saved += 1
    ds.status = "raw"
    db.session.commit()
    return ok({"saved": saved}, f"已保存 {saved} 张")


@datasets_bp.post("/<int:did>/extract-frames")
@login_required
def extract_frames(did: int):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    f = request.files.get("file")
    if f is None or not f.filename:
        return fail("请选择视频")
    interval = max(1, int(request.form.get("frameInterval") or 10))
    max_frames = max(1, int(request.form.get("maxFrames") or 80))
    tmp = Config.VIDEO_FOLDER / f"extract_{did}_{Path(f.filename).name}"
    Config.VIDEO_FOLDER.mkdir(parents=True, exist_ok=True)
    f.save(tmp)
    cap = cv2.VideoCapture(str(tmp))
    img_dir = _raw_images(ds)
    saved = 0
    idx = 0
    while saved < max_frames:
        ok_frame, frame = cap.read()
        if not ok_frame:
            break
        if idx % interval == 0:
            cv2.imwrite(str(img_dir / f"frame_{saved:04d}.jpg"), frame)
            saved += 1
        idx += 1
    cap.release()
    tmp.unlink(missing_ok=True)
    ds.status = "raw"
    db.session.commit()
    return ok({"saved": saved}, f"抽帧 {saved} 张")


@datasets_bp.get("/<int:did>/samples")
@login_required
def list_samples(did: int):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    img_dir = _raw_images(ds)
    lbl_dir = _raw_labels(ds)
    items = []
    for p in sorted(img_dir.iterdir()):
        if p.suffix.lower() not in Config.IMAGE_ALLOWED_EXT:
            continue
        lbl = lbl_dir / f"{p.stem}.txt"
        lines = []
        if lbl.exists():
            lines = [line for line in lbl.read_text(encoding="utf-8").splitlines() if line.strip()]
        class_ids = []
        for line in lines:
            parts = line.split()
            if not parts:
                continue
            try:
                class_ids.append(int(float(parts[0])))
            except ValueError:
                continue
        items.append({
            "stem": p.stem,
            "name": p.name,
            "annotated": bool(lines),
            "boxCount": len(lines),
            "classIds": sorted(set(class_ids)),
        })
    annotated = sum(1 for i in items if i["annotated"])
    names = _classes(ds)
    return ok({
        "samples": items,
        "classNames": names,
        "colors": load_dataset_colors(_ds_dir(ds), names),
        "folderPath": str(img_dir),
        "stats": {"total": len(items), "annotated": annotated, "unannotated": len(items) - annotated},
    })


@datasets_bp.get("/<int:did>/image/<stem>")
@login_required
def get_image(did: int, stem: str):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    p = _find_image(ds, stem)
    if p is None:
        return fail("图片不存在", 404)
    return send_file(p)


@datasets_bp.get("/<int:did>/boxes")
@login_required
def get_boxes(did: int):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    stem = (request.args.get("stem") or "").strip()
    if not stem:
        return fail("缺少图片名")
    return ok({"boxes": _read_boxes(_raw_labels(ds) / f"{stem}.txt"), "stem": stem})


@datasets_bp.put("/<int:did>/boxes")
@login_required
def put_boxes(did: int):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    data = request.get_json(silent=True) or {}
    stem = (data.get("stem") or "").strip()
    if not stem:
        return fail("缺少图片名")
    boxes = data.get("boxes") or []
    _write_boxes(_raw_labels(ds) / f"{stem}.txt", boxes)
    _sync_yolo_labels(ds, stem, boxes)
    return ok({"stem": stem, "boxCount": len(boxes)}, "已保存")


@datasets_bp.get("/<int:did>/labels/<stem>")
@login_required
def get_labels(did: int, stem: str):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    return ok({"boxes": _read_boxes(_raw_labels(ds) / f"{stem}.txt")})


@datasets_bp.put("/<int:did>/labels/<stem>")
@login_required
def put_labels(did: int, stem: str):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    data = request.get_json(silent=True) or {}
    boxes = data.get("boxes") or []
    _write_boxes(_raw_labels(ds) / f"{stem}.txt", boxes)
    _sync_yolo_labels(ds, stem, boxes)
    return ok({"stem": stem, "boxCount": len(boxes)}, "已保存")


@datasets_bp.post("/<int:did>/annotate/prelabel")
@login_required
def prelabel(did: int):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    names = _classes(ds)
    if not names:
        return fail("请先填写检测类别")
    data = request.get_json(silent=True) or {}
    model_id = data.get("modelId")
    if not model_id:
        return fail("请选择预标模型")
    m = db.session.get(DetectModel, int(model_id))
    if m is None:
        return fail("模型不存在", 404)
    weight = resolve_weight(m)
    if not weight:
        return fail("预标模型没有可用权重")
    conf = float(data.get("conf") or 0.25)
    apply_all = bool(data.get("applyAll"))
    stems = []
    if apply_all:
        img_dir = _raw_images(ds)
        stems = [p.stem for p in sorted(img_dir.iterdir()) if p.suffix.lower() in Config.IMAGE_ALLOWED_EXT]
    else:
        stem = data.get("stem")
        if not stem:
            return fail("缺少图片 stem")
        stems = [stem]
    labeled = 0
    last_boxes = []
    for stem in stems:
        img = _find_image(ds, stem)
        if img is None:
            continue
        boxes = yolo_prelabel(weight, img, names, conf=conf)
        _write_boxes(_raw_labels(ds) / f"{stem}.txt", boxes)
        labeled += 1
        last_boxes = boxes
    return ok({"labeled": labeled, "boxes": last_boxes}, f"预标完成 {labeled} 张")


@datasets_bp.post("/<int:did>/annotate/sam")
@login_required
def sam_click(did: int):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    data = request.get_json(silent=True) or {}
    stem = data.get("stem")
    if not stem:
        return fail("缺少图片 stem")
    img = _find_image(ds, stem)
    if img is None:
        return fail("图片不存在", 404)
    try:
        box = sam_click_box(
            img,
            float(data.get("x") or 0),
            float(data.get("y") or 0),
            int(data.get("cls") or 0),
        )
    except Exception as exc:  # noqa: BLE001
        return fail(f"SAM 失败：{exc}", 500)
    return ok({"box": box})


@datasets_bp.post("/<int:did>/build")
@login_required
def build_dataset(did: int):
    ds = db.session.get(Dataset, did)
    if ds is None:
        return fail("数据集不存在", 404)
    names = _classes(ds)
    if not names:
        return fail("请先填写检测类别")
    img_dir = _raw_images(ds)
    lbl_dir = _raw_labels(ds)
    pairs = []
    for img in sorted(img_dir.iterdir()):
        if img.suffix.lower() not in Config.IMAGE_ALLOWED_EXT:
            continue
        lbl = lbl_dir / f"{img.stem}.txt"
        if not lbl.exists() or not lbl.read_text(encoding="utf-8").strip():
            continue
        pairs.append((img, lbl))
    if len(pairs) < 2:
        return fail("至少需要 2 张已标注图片才能构建")
    yolo_dir = _ds_dir(ds) / "yolo"
    if yolo_dir.exists():
        shutil.rmtree(yolo_dir)
    for split in ("train", "val"):
        (yolo_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (yolo_dir / "labels" / split).mkdir(parents=True, exist_ok=True)
    random.seed(42)
    random.shuffle(pairs)
    n_train = max(1, int(len(pairs) * ds.split_ratio))
    if n_train >= len(pairs):
        n_train = len(pairs) - 1
    splits = {"train": pairs[:n_train], "val": pairs[n_train:]}
    for split, items in splits.items():
        for img, lbl in items:
            shutil.copy2(img, yolo_dir / "images" / split / img.name)
            shutil.copy2(lbl, yolo_dir / "labels" / split / lbl.name)
    names_txt = ", ".join(repr(n) for n in names)
    (yolo_dir / "data.yaml").write_text(
        f"path: {yolo_dir.as_posix()}\n"
        f"train: images/train\n"
        f"val: images/val\n"
        f"nc: {len(names)}\n"
        f"names: [{names_txt}]\n",
        encoding="utf-8",
    )
    ds.train_count = len(splits["train"])
    ds.val_count = len(splits["val"])
    ds.status = "ready"
    db.session.commit()
    return ok(_to_dict(ds), f"构建完成 train={ds.train_count} val={ds.val_count}")

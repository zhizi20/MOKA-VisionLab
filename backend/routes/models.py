import re
import shutil
import threading
import uuid
from pathlib import Path

from flask import Blueprint, current_app, request

from config import Config
from extensions import db
from models import DetectModel
from security import login_required
from storage import builtin_weight_path, custom_model_dir
from utils import fail, ok
from weight_download import download_jobs, download_jobs_lock, download_weight
from yolo_catalog import BUILTIN_YOLO

models_bp = Blueprint("models", __name__, url_prefix="/api/models")


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", (text or "").strip()).strip("-").lower()
    return s or "model"


def _to_dict(m: DetectModel) -> dict:
    path = Path(m.file_path) if m.file_path else None
    has_file = bool(path and path.exists() and path.stat().st_size > 1024)
    return {
        "id": m.id,
        "name": m.name,
        "modelKey": m.model_key,
        "version": m.version,
        "category": m.category,
        "library": m.library,
        "filePath": m.file_path,
        "fileSize": m.file_size,
        "hasWeight": has_file,
        "fileMissing": bool(m.file_path) and not has_file,
        "description": m.description,
        "status": m.status,
        "source": m.source,
        "createTime": m.create_time.strftime("%Y-%m-%d %H:%M:%S") if m.create_time else "",
    }


def resolve_weight(m: DetectModel) -> str | None:
    if m.status != "0":
        return None
    if not m.file_path:
        return None
    path = Path(m.file_path)
    if path.exists() and path.stat().st_size > 1024:
        return str(path)
    return None


@models_bp.get("")
@login_required
def list_models():
    name = (request.args.get("name") or "").strip()
    q = DetectModel.query.order_by(DetectModel.id.desc())
    if name:
        q = q.filter(DetectModel.name.contains(name))
    rows = [_to_dict(m) for m in q.all()]
    return ok({"rows": rows, "total": len(rows)})


@models_bp.post("")
@login_required
def add_model():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return fail("请填写模型名称")
    key = (data.get("modelKey") or "").strip() or _slug(name)
    if DetectModel.query.filter_by(model_key=key).first():
        return fail("模型标识已存在")
    m = DetectModel(
        name=name,
        model_key=key,
        version=data.get("version") or "1.0",
        category=data.get("category") or "目标检测",
        description=data.get("description") or "",
        status=data.get("status") or "0",
        source="upload",
    )
    db.session.add(m)
    db.session.commit()
    return ok(_to_dict(m), "已创建")


@models_bp.put("/<int:mid>")
@login_required
def update_model(mid: int):
    m = db.session.get(DetectModel, mid)
    if m is None:
        return fail("模型不存在", 404)
    data = request.get_json(silent=True) or {}
    m.name = (data.get("name") or m.name).strip()
    m.version = data.get("version") or m.version
    m.category = data.get("category") or m.category
    m.description = data.get("description") if "description" in data else m.description
    m.status = data.get("status") or m.status
    db.session.commit()
    return ok(_to_dict(m), "已更新")


@models_bp.delete("/<int:mid>")
@login_required
def remove_model(mid: int):
    m = db.session.get(DetectModel, mid)
    if m is None:
        return fail("模型不存在", 404)
    if m.file_path:
        path = Path(m.file_path)
        if m.source == "builtin":
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(path.parent, ignore_errors=True)
    shutil.rmtree(Config.MODEL_FOLDER / m.model_key, ignore_errors=True)
    shutil.rmtree(custom_model_dir(m.model_key), ignore_errors=True)
    db.session.delete(m)
    db.session.commit()
    return ok(message="已删除")


@models_bp.post("/<int:mid>/upload")
@login_required
def upload_weight(mid: int):
    m = db.session.get(DetectModel, mid)
    if m is None:
        return fail("模型不存在", 404)
    f = request.files.get("file")
    if f is None or not f.filename:
        return fail("请选择权重文件")
    ext = Path(f.filename).suffix.lower()
    if ext not in Config.MODEL_ALLOWED_EXT:
        return fail("仅支持 .pt 权重")
    dest_dir = custom_model_dir(m.model_key)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"weights{ext}"
    f.save(dest)
    m.file_path = str(dest)
    m.file_size = dest.stat().st_size
    m.source = "upload"
    db.session.commit()
    return ok(_to_dict(m), "权重已上传")


def _weight_version(weights: str) -> str:
    if weights.startswith("yolo26"):
        return "26"
    if weights.startswith("yolo12"):
        return "12"
    if weights.startswith("yolo11"):
        return "11"
    if "v8" in weights:
        return "8"
    return "1.0"


def _run_weight_download(app, job_id: str, mid: int, filename: str, dest: Path):
    try:
        download_weight(job_id, filename, dest)
        with app.app_context():
            m = db.session.get(DetectModel, mid)
            if m and dest.exists():
                m.file_path = str(dest)
                m.file_size = dest.stat().st_size
                db.session.commit()
    except Exception:  # noqa: BLE001
        return


def _start_weight_download(m: DetectModel, dest: Path, filename: str) -> str:
    job_id = uuid.uuid4().hex
    with download_jobs_lock:
        download_jobs[job_id] = {
            "status": "queued",
            "modelId": m.id,
            "filename": filename,
            "progress": 0,
            "downloaded": 0,
            "total": 0,
            "error": None,
        }
    app = current_app._get_current_object()
    threading.Thread(
        target=_run_weight_download,
        args=(app, job_id, m.id, filename, dest),
        daemon=True,
    ).start()
    return job_id


@models_bp.get("/builtins")
@login_required
def list_builtins():
    return ok(BUILTIN_YOLO)


@models_bp.get("/download-progress/<job_id>")
@login_required
def weight_progress(job_id: str):
    with download_jobs_lock:
        job = download_jobs.get(job_id)
    if job is None:
        return fail("下载任务不存在", 404)
    return ok(job)


@models_bp.post("/<int:mid>/download-weight")
@login_required
def download_model_weight(mid: int):
    m = db.session.get(DetectModel, mid)
    if m is None:
        return fail("模型不存在", 404)
    dest = Path(m.file_path) if m.file_path else (
        builtin_weight_path(f"{m.model_key}.pt") if m.source == "builtin" else custom_model_dir(m.model_key) / f"{m.model_key}.pt"
    )
    if dest.exists() and dest.stat().st_size > 1024:
        m.file_size = dest.stat().st_size
        db.session.commit()
        return ok({"model": _to_dict(m), "jobId": None}, "权重已在本地")
    filename = dest.name if dest.suffix == ".pt" else f"{m.model_key}.pt"
    dest = dest if dest.suffix == ".pt" else dest.parent / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    m.file_path = str(dest)
    db.session.commit()
    job_id = _start_weight_download(m, dest, filename)
    return ok({"model": _to_dict(m), "jobId": job_id}, "已开始下载权重（GitHub 超时会自动换镜像）")


@models_bp.post("/register-builtin")
@login_required
def register_builtin():
    payload = request.get_json(silent=True) or {}
    name = (request.form.get("name") or payload.get("name") or "YOLO26n").strip()
    weights = (request.form.get("weights") or payload.get("weights") or "yolo26n.pt").strip()
    if not weights.endswith(".pt"):
        return fail("仅支持 Ultralytics .pt 内置权重")
    key = _slug(Path(weights).stem)
    dest = builtin_weight_path(weights)
    dest.parent.mkdir(parents=True, exist_ok=True)
    exist = DetectModel.query.filter_by(model_key=key).first()
    if exist:
        m = exist
        if dest.exists() and dest.stat().st_size > 1024:
            m.file_path = str(dest)
            m.file_size = dest.stat().st_size
            db.session.commit()
            return ok({"model": _to_dict(m), "jobId": None}, "已存在，权重已在本地")
        m.file_path = str(dest)
        db.session.commit()
        job_id = _start_weight_download(m, dest, weights)
        return ok({"model": _to_dict(m), "jobId": job_id}, "已开始下载权重（GitHub 超时会自动换镜像）")
    m = DetectModel(
        name=name,
        model_key=key,
        version=_weight_version(weights),
        category="目标检测",
        file_path=str(dest),
        description=f"Ultralytics 官方 {weights}，从镜像下载",
        source="builtin",
        status="0",
    )
    db.session.add(m)
    db.session.commit()
    if dest.exists() and dest.stat().st_size > 1024:
        m.file_size = dest.stat().st_size
        db.session.commit()
        return ok({"model": _to_dict(m), "jobId": None}, "已登记，权重已在本地")
    job_id = _start_weight_download(m, dest, weights)
    return ok({"model": _to_dict(m), "jobId": job_id}, "已开始下载权重（GitHub 超时会自动换镜像）")

import re
import shutil
from pathlib import Path

from flask import Blueprint, request

from config import Config
from extensions import db
from models import DetectModel
from security import login_required
from utils import fail, ok

models_bp = Blueprint("models", __name__, url_prefix="/api/models")


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", (text or "").strip()).strip("-").lower()
    return s or "model"


def _to_dict(m: DetectModel) -> dict:
    path = Path(m.file_path) if m.file_path else None
    has_file = bool(path and path.exists())
    return {
        "id": m.id,
        "name": m.name,
        "modelKey": m.model_key,
        "version": m.version,
        "category": m.category,
        "library": m.library,
        "filePath": m.file_path,
        "fileSize": m.file_size,
        "hasWeight": has_file or m.source == "builtin",
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
    if path.exists():
        return str(path)
    if m.source == "builtin":
        return path.name
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
    folder = Config.MODEL_FOLDER / m.model_key
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
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
    dest_dir = Config.MODEL_FOLDER / m.model_key
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"weights{ext}"
    f.save(dest)
    m.file_path = str(dest)
    m.file_size = dest.stat().st_size
    m.source = "upload"
    db.session.commit()
    return ok(_to_dict(m), "权重已上传")


@models_bp.post("/register-builtin")
@login_required
def register_builtin():
    name = (request.form.get("name") or "YOLO11n").strip()
    weights = (request.form.get("weights") or "yolo11n.pt").strip()
    if not weights.endswith(".pt"):
        return fail("仅支持 Ultralytics .pt 内置权重")
    key = _slug(Path(weights).stem)
    exist = DetectModel.query.filter_by(model_key=key).first()
    if exist:
        return ok(_to_dict(exist), "已存在")
    dest_dir = Config.MODEL_FOLDER / key
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / weights
    m = DetectModel(
        name=name,
        model_key=key,
        version="11",
        category="目标检测",
        file_path=str(dest),
        description=f"Ultralytics 内置 {weights}，首次检测时自动下载",
        source="builtin",
        status="0",
    )
    db.session.add(m)
    db.session.commit()
    return ok(_to_dict(m), "已登记，首次检测将自动拉取权重")

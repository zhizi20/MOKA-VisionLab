import random
import shutil
from pathlib import Path

import cv2
from flask import Blueprint, request, send_file

from config import Config
from extensions import db
from models import Dataset, DetectModel
from routes.models import resolve_weight
from security import login_required
from smart_label import sam_click_box, yolo_prelabel
from utils import fail, ok

datasets_bp = Blueprint("datasets", __name__, url_prefix="/api/datasets")


def _ds_dir(ds: Dataset) -> Path:
    return Config.DATASET_FOLDER / str(ds.id)


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


def _to_dict(ds: Dataset) -> dict:
    return {
        "id": ds.id,
        "name": ds.name,
        "classNames": _classes(ds),
        "status": ds.status,
        "trainCount": ds.train_count,
        "valCount": ds.val_count,
        "splitRatio": ds.split_ratio,
        "description": ds.description,
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
    lines = []
    for b in boxes:
        lines.append(f"{int(b['cls'])} {b['cx']:.6f} {b['cy']:.6f} {b['w']:.6f} {b['h']:.6f}")
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


@datasets_bp.get("")
@login_required
def list_datasets():
    rows = [_to_dict(d) for d in Dataset.query.order_by(Dataset.id.desc()).all()]
    return ok({"rows": rows, "total": len(rows)})


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
    ds.name = (data.get("name") or ds.name).strip()
    if "classNames" in data:
        ds.class_names = ",".join(str(c).strip() for c in (data.get("classNames") or []) if str(c).strip())
    if "splitRatio" in data:
        ds.split_ratio = float(data.get("splitRatio") or ds.split_ratio)
    if "description" in data:
        ds.description = data.get("description") or ""
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
        boxes = 0
        if lbl.exists():
            boxes = sum(1 for line in lbl.read_text(encoding="utf-8").splitlines() if line.strip())
        items.append({"stem": p.stem, "name": p.name, "annotated": boxes > 0, "boxCount": boxes})
    annotated = sum(1 for i in items if i["annotated"])
    return ok({
        "samples": items,
        "classNames": _classes(ds),
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
    _write_boxes(_raw_labels(ds) / f"{stem}.txt", data.get("boxes") or [])
    return ok(message="已保存")


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

import threading
import uuid
from pathlib import Path

from flask import Blueprint, request, send_file

from config import Config
from extensions import db
from infer import detect_image, detect_video, video_jobs, video_jobs_lock
from models import DetectModel
from routes.models import resolve_weight
from security import login_required
from utils import fail, ok

detect_bp = Blueprint("detect", __name__, url_prefix="/api/detect")


def _weight_or_fail(mid: int):
    m = db.session.get(DetectModel, mid)
    if m is None:
        return None, fail("模型不存在", 404)
    if m.status != "0":
        return None, fail("模型已停用")
    weight = resolve_weight(m)
    if not weight:
        return None, fail("请先上传权重")
    return weight, None


@detect_bp.post("/<int:mid>/image")
@login_required
def detect_image_api(mid: int):
    weight, err = _weight_or_fail(mid)
    if err:
        return err
    f = request.files.get("file")
    if f is None or not f.filename:
        return fail("请选择图片")
    conf = float(request.form.get("conf") or 0.25)
    try:
        result = detect_image(weight, f.read(), conf=conf)
    except Exception as exc:  # noqa: BLE001
        return fail(f"推理失败：{exc}", 500)
    return ok(result, "检测完成")


@detect_bp.post("/<int:mid>/video")
@login_required
def detect_video_api(mid: int):
    weight, err = _weight_or_fail(mid)
    if err:
        return err
    f = request.files.get("file")
    if f is None or not f.filename:
        return fail("请选择视频")
    ext = Path(f.filename).suffix.lower()
    if ext not in Config.VIDEO_ALLOWED_EXT:
        return fail("不支持的视频格式")
    conf = float(request.form.get("conf") or 0.25)
    job_id = uuid.uuid4().hex
    src = Config.VIDEO_FOLDER / f"{job_id}{ext}"
    dst = Config.OUTPUT_FOLDER / f"{job_id}_det.mp4"
    Config.VIDEO_FOLDER.mkdir(parents=True, exist_ok=True)
    Config.OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    f.save(src)
    threading.Thread(
        target=detect_video,
        args=(job_id, weight, str(src), str(dst), conf),
        daemon=True,
    ).start()
    return ok({"jobId": job_id}, "任务已启动")


@detect_bp.get("/<int:mid>/video-progress/<job_id>")
@login_required
def video_progress(mid: int, job_id: str):
    with video_jobs_lock:
        job = video_jobs.get(job_id)
    if job is None:
        return fail("任务不存在", 404)
    total = job.get("total") or 0
    processed = job.get("processed") or 0
    pct = int(processed * 100 / total) if total else (100 if job["status"] == "done" else 0)
    return ok({**job, "progress": pct})


@detect_bp.get("/output/<name>")
@login_required
def download_output(name: str):
    path = Config.OUTPUT_FOLDER / Path(name).name
    if not path.exists():
        return fail("文件不存在", 404)
    return send_file(path, as_attachment=True, download_name=path.name)

import json
import threading
from pathlib import Path

from flask import Blueprint, current_app, request
from ultralytics import YOLO

from config import Config
from extensions import db
from models import Dataset, DetectModel, TrainJob
from security import login_required
from utils import fail, ok

jobs_bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")


def _job_dict(job: TrainJob, dataset_name: str = "") -> dict:
    metrics = {}
    if job.metrics:
        try:
            metrics = json.loads(job.metrics)
        except json.JSONDecodeError:
            metrics = {}
    return {
        "id": job.id,
        "jobName": job.job_name,
        "datasetId": job.dataset_id,
        "datasetName": dataset_name,
        "baseModel": job.base_model,
        "epochs": job.epochs,
        "batch": job.batch,
        "imgsz": job.imgsz,
        "device": job.device,
        "status": job.status,
        "progress": job.progress,
        "currentEpoch": job.current_epoch,
        "metrics": metrics,
        "logTail": job.log_tail,
        "error": job.error,
        "resultModelId": job.result_model_id,
        "createTime": job.create_time.strftime("%Y-%m-%d %H:%M:%S") if job.create_time else "",
    }


@jobs_bp.get("")
@login_required
def list_jobs():
    jobs = TrainJob.query.order_by(TrainJob.id.desc()).all()
    ds_map = {d.id: d.name for d in Dataset.query.all()}
    rows = [_job_dict(j, ds_map.get(j.dataset_id, "")) for j in jobs]
    return ok({"rows": rows, "total": len(rows)})


@jobs_bp.get("/base-models")
@login_required
def base_models():
    return ok([
        {"value": "yolo11n.pt", "label": "YOLO11n（推荐 CPU）"},
        {"value": "yolo11s.pt", "label": "YOLO11s"},
        {"value": "yolov8n.pt", "label": "YOLOv8n"},
        {"value": "yolov8s.pt", "label": "YOLOv8s"},
    ])


@jobs_bp.post("")
@login_required
def add_job():
    data = request.get_json(silent=True) or {}
    name = (data.get("jobName") or "").strip()
    dataset_id = data.get("datasetId")
    if not name or not dataset_id:
        return fail("请填写任务名并选择数据集")
    ds = db.session.get(Dataset, int(dataset_id))
    if ds is None:
        return fail("数据集不存在", 404)
    if ds.status != "ready":
        return fail("请先构建数据集")
    job = TrainJob(
        job_name=name,
        dataset_id=ds.id,
        base_model=data.get("baseModel") or "yolo11n.pt",
        epochs=int(data.get("epochs") or 20),
        batch=int(data.get("batch") or 4),
        imgsz=int(data.get("imgsz") or 640),
        device=data.get("device") or "cpu",
    )
    db.session.add(job)
    db.session.commit()
    return ok(_job_dict(job, ds.name), "已创建")


@jobs_bp.post("/<int:jid>/start")
@login_required
def start_job(jid: int):
    job = db.session.get(TrainJob, jid)
    if job is None:
        return fail("任务不存在", 404)
    if job.status == "running":
        return fail("正在训练")
    job.status = "running"
    job.progress = 0
    job.error = ""
    db.session.commit()
    app = current_app._get_current_object()
    threading.Thread(target=_run_train, args=(app, jid), daemon=True).start()
    return ok(message="已启动")


@jobs_bp.get("/<int:jid>")
@login_required
def get_job(jid: int):
    job = db.session.get(TrainJob, jid)
    if job is None:
        return fail("任务不存在", 404)
    ds = db.session.get(Dataset, job.dataset_id)
    return ok(_job_dict(job, ds.name if ds else ""))


@jobs_bp.delete("/<int:jid>")
@login_required
def remove_job(jid: int):
    job = db.session.get(TrainJob, jid)
    if job is None:
        return fail("任务不存在", 404)
    if job.status == "running":
        return fail("训练中不可删除")
    db.session.delete(job)
    db.session.commit()
    return ok(message="已删除")


def _run_train(app, job_id: int):
    with app.app_context():
        try:
            job = db.session.get(TrainJob, job_id)
            ds = db.session.get(Dataset, job.dataset_id)
            yaml_path = Config.DATASET_FOLDER / str(ds.id) / "yolo" / "data.yaml"
            if not yaml_path.exists():
                raise RuntimeError("找不到 data.yaml，请先构建数据集")
            out_dir = Config.TRAINING_FOLDER / f"job_{job_id}"
            out_dir.mkdir(parents=True, exist_ok=True)

            def on_fit_epoch(trainer):
                ep = int(getattr(trainer, "epoch", 0)) + 1
                total = int(getattr(trainer, "epochs", job.epochs) or job.epochs)
                job2 = db.session.get(TrainJob, job_id)
                job2.current_epoch = ep
                job2.progress = min(99, int(ep * 100 / max(total, 1)))
                metrics = getattr(trainer, "metrics", None) or {}
                serial = {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}
                job2.metrics = json.dumps(serial, ensure_ascii=False)
                db.session.commit()

            model = YOLO(job.base_model)
            model.add_callback("on_fit_epoch_end", on_fit_epoch)
            model.train(
                data=str(yaml_path),
                epochs=job.epochs,
                batch=job.batch,
                imgsz=job.imgsz,
                device=job.device,
                project=str(out_dir),
                name="exp",
                exist_ok=True,
                verbose=False,
            )
            best = out_dir / "exp" / "weights" / "best.pt"
            job = db.session.get(TrainJob, job_id)
            if best.exists():
                key = f"train-job-{job_id}"
                dest_dir = Config.MODEL_FOLDER / key
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / "best.pt"
                dest.write_bytes(best.read_bytes())
                exist = DetectModel.query.filter_by(model_key=key).first()
                if exist is None:
                    m = DetectModel(
                        name=f"{job.job_name}-best",
                        model_key=key,
                        version="1.0",
                        category="自训练",
                        file_path=str(dest),
                        file_size=dest.stat().st_size,
                        description=f"由训练任务 #{job_id} 产出",
                        source="train",
                        status="0",
                    )
                    db.session.add(m)
                    db.session.commit()
                    job.result_model_id = m.id
                else:
                    exist.file_path = str(dest)
                    exist.file_size = dest.stat().st_size
                    db.session.commit()
                    job.result_model_id = exist.id
            job.status = "done"
            job.progress = 100
            db.session.commit()
        except Exception as exc:  # noqa: BLE001
            job = db.session.get(TrainJob, job_id)
            if job:
                job.status = "failed"
                job.error = str(exc)
                db.session.commit()

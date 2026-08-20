import csv
import json
import os
import threading
from pathlib import Path

from flask import Blueprint, current_app, request, send_file
from ultralytics import YOLO

from config import Config
from extensions import db
from models import Dataset, DetectModel, TrainJob
from routes.models import resolve_weight
from security import login_required
from storage import assign_train_folder, builtin_weight_path, dataset_dir, trained_model_dir, training_exp_dir
from utils import fail, ok
from weight_download import download_weight, find_existing_weight
from yolo_catalog import BUILTIN_YOLO, builtin_label

jobs_bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")

_train_lock = threading.Lock()


def _is_cpu(device: str) -> bool:
    return (device or "cpu").strip().lower() in {"cpu", "-1", ""}


def _cpu_caps() -> tuple[int, int]:
    if Config.CPU_SAFE:
        return Config.CPU_MAX_BATCH, Config.CPU_MAX_IMGSZ
    return 32, 1280


def _clamp_job_params(job: TrainJob) -> list[str]:
    notes: list[str] = []
    job.epochs = max(1, min(int(job.epochs or 20), 300))
    job.batch = max(1, min(int(job.batch or 4), 32))
    job.imgsz = max(320, min(int(job.imgsz or 640), 1280))
    if not _is_cpu(job.device):
        return notes
    job.device = "cpu"
    max_batch, max_imgsz = _cpu_caps()
    if job.batch > max_batch:
        job.batch = max_batch
        notes.append(f"CPU 训练 batch 已限制为 {max_batch}，避免把系统卡死")
    if job.imgsz > max_imgsz:
        job.imgsz = max_imgsz
        notes.append(f"CPU 训练 imgsz 已限制为 {max_imgsz}")
    return notes


def _limit_compute_threads(n: int | None = None) -> None:
    if n is None:
        n = Config.CPU_TORCH_THREADS
    n = max(1, min(n, os.cpu_count() or 4))
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[key] = str(n)
    try:
        import torch

        torch.set_num_threads(n)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
    except Exception:
        pass


def _set_windows_priority(below_normal: bool) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetCurrentProcess()
        value = 0x00004000 if below_normal else 0x00000020
        ctypes.windll.kernel32.SetPriorityClass(handle, value)
    except Exception:
        pass


def mark_interrupted_jobs() -> None:
    stuck = TrainJob.query.filter_by(status="running").all()
    if not stuck:
        return
    for job in stuck:
        job.status = "failed"
        job.error = "服务重启，训练中断。CPU 训练请用 batch 2～4，否则容易卡死整台电脑。"
    db.session.commit()


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
        "baseModelLabel": _base_label(job.base_model),
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
        "folder": job.folder or "",
        "createTime": job.create_time.strftime("%Y-%m-%d %H:%M:%S") if job.create_time else "",
    }


@jobs_bp.get("")
@login_required
def list_jobs():
    jobs = TrainJob.query.order_by(TrainJob.id.desc()).all()
    ds_map = {d.id: d.name for d in Dataset.query.all()}
    rows = [_job_dict(j, ds_map.get(j.dataset_id, "")) for j in jobs]
    return ok({"rows": rows, "total": len(rows)})


def _base_label(spec: str) -> str:
    spec = spec or ""
    if spec.startswith("id:"):
        try:
            mid = int(spec.split(":", 1)[1])
        except ValueError:
            return spec
        m = db.session.get(DetectModel, mid)
        return m.name if m else spec
    return builtin_label(spec)


def _exp_dir(job_id: int) -> Path:
    job = db.session.get(TrainJob, job_id)
    if job is None:
        return Config.TRAINING_FOLDER / f"job_{job_id}" / "exp"
    return training_exp_dir(job)


def _read_results_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            rows.append({(k or "").strip(): (v or "").strip() for k, v in raw.items() if k and k.strip()})
    return rows


PLOT_LABELS = {
    "results.png": "训练曲线",
    "confusion_matrix.png": "混淆矩阵",
    "confusion_matrix_normalized.png": "归一化混淆矩阵",
    "F1_curve.png": "F1 曲线",
    "BoxF1_curve.png": "F1 曲线",
    "PR_curve.png": "PR 曲线",
    "BoxPR_curve.png": "PR 曲线",
    "P_curve.png": "Precision 曲线",
    "BoxP_curve.png": "Precision 曲线",
    "R_curve.png": "Recall 曲线",
    "BoxR_curve.png": "Recall 曲线",
    "labels.jpg": "标签分布",
    "train_batch0.jpg": "训练 batch 样例",
    "val_batch0_labels.jpg": "验证标签",
    "val_batch0_pred.jpg": "验证预测",
}


def _list_plots(job_id: int) -> list[dict]:
    exp = _exp_dir(job_id)
    if not exp.exists():
        return []
    items = []
    for path in sorted(exp.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue
        items.append({
            "name": path.name,
            "label": PLOT_LABELS.get(path.name, path.stem),
            "size": path.stat().st_size,
            "mtime": int(path.stat().st_mtime),
        })
    return items


def resolve_train_weight(spec: str) -> str:
    spec = (spec or "").strip()
    if spec.startswith("id:"):
        m = db.session.get(DetectModel, int(spec.split(":", 1)[1]))
        if m is None:
            raise RuntimeError("所选基座模型不存在")
        weight = resolve_weight(m)
        if not weight:
            raise RuntimeError("所选基座模型没有可用权重")
        return weight
    filename = Path(spec or "yolo11n.pt").name
    existing = find_existing_weight(filename, Config.MODEL_FOLDER)
    if existing:
        return str(existing)
    dest = builtin_weight_path(filename)
    download_weight(f"train-{filename}", filename, dest)
    return str(dest)


@jobs_bp.get("/base-models")
@login_required
def base_models():
    rows = []
    for item in BUILTIN_YOLO:
        hint = f" · {item['hint']}" if item.get("hint") else ""
        rows.append({
            "value": item["value"],
            "label": f"{item['label']}{hint}",
            "group": f"内置 {item['family']}",
        })
    for m in DetectModel.query.order_by(DetectModel.id.desc()).all():
        if m.status != "0" or m.source == "builtin":
            continue
        weight = resolve_weight(m)
        if not weight:
            continue
        rows.append({
            "value": f"id:{m.id}",
            "label": f"{m.name}（{m.source}）",
            "group": "已有模型",
        })
    return ok(rows)


@jobs_bp.get("/limits")
@login_required
def train_limits():
    max_batch, max_imgsz = _cpu_caps()
    return ok({
        "cpuSafe": Config.CPU_SAFE,
        "cpuMaxBatch": max_batch,
        "cpuMaxImgsz": max_imgsz,
        "gpuMaxBatch": 32,
        "gpuMaxImgsz": 1280,
        "maxEpochs": 300,
    })


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
        base_model=data.get("baseModel") or "yolo26n.pt",
        epochs=int(data.get("epochs") or 20),
        batch=int(data.get("batch") or 4),
        imgsz=int(data.get("imgsz") or 640),
        device=data.get("device") or "cpu",
    )
    notes = _clamp_job_params(job)
    db.session.add(job)
    db.session.commit()
    assign_train_folder(job)
    db.session.commit()
    msg = "已创建"
    if notes:
        msg = "已创建（" + "；".join(notes) + "）"
    return ok(_job_dict(job, ds.name), msg)


@jobs_bp.post("/<int:jid>/start")
@login_required
def start_job(jid: int):
    job = db.session.get(TrainJob, jid)
    if job is None:
        return fail("任务不存在", 404)
    if job.status == "running":
        return fail("正在训练")
    if not Config.ALLOW_PARALLEL_TRAIN:
        other = TrainJob.query.filter(TrainJob.status == "running", TrainJob.id != jid).first()
        if other:
            return fail("已有训练任务在运行，并行训练容易把电脑卡死")
    notes = _clamp_job_params(job)
    job.status = "running"
    job.progress = 0
    job.error = ""
    db.session.commit()
    app = current_app._get_current_object()
    threading.Thread(target=_run_train, args=(app, jid), daemon=True).start()
    msg = "已启动"
    if notes:
        msg = "已启动（" + "；".join(notes) + "）"
    return ok(message=msg)


@jobs_bp.get("/<int:jid>")
@login_required
def get_job(jid: int):
    job = db.session.get(TrainJob, jid)
    if job is None:
        return fail("任务不存在", 404)
    ds = db.session.get(Dataset, job.dataset_id)
    data = _job_dict(job, ds.name if ds else "")
    data["plots"] = _list_plots(jid)
    data["history"] = _read_results_csv(_exp_dir(jid) / "results.csv")
    return ok(data)


@jobs_bp.get("/<int:jid>/plots/<name>")
@login_required
def job_plot(jid: int, name: str):
    job = db.session.get(TrainJob, jid)
    if job is None:
        return fail("任务不存在", 404)
    exp = _exp_dir(jid).resolve()
    path = (exp / Path(name).name).resolve()
    try:
        path.relative_to(exp)
    except ValueError:
        return fail("图片不存在", 404)
    if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        return fail("图片不存在", 404)
    return send_file(path)


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
    use_lock = not Config.ALLOW_PARALLEL_TRAIN
    if use_lock and not _train_lock.acquire(blocking=False):
        with app.app_context():
            job = db.session.get(TrainJob, job_id)
            if job:
                job.status = "failed"
                job.error = "已有训练在进行"
                db.session.commit()
        return
    if Config.CPU_SAFE:
        _set_windows_priority(True)
    with app.app_context():
        try:
            job = db.session.get(TrainJob, job_id)
            ds = db.session.get(Dataset, job.dataset_id)
            yaml_path = dataset_dir(ds) / "yolo" / "data.yaml"
            if not yaml_path.exists():
                raise RuntimeError("找不到 data.yaml，请先构建数据集")
            _clamp_job_params(job)
            job.log_tail = "正在准备基座权重（GitHub 超时会自动换镜像）..."
            db.session.commit()
            out_dir = assign_train_folder(job)
            db.session.commit()
            cpu = _is_cpu(job.device)
            cpu_safe = cpu and Config.CPU_SAFE
            if cpu_safe:
                _limit_compute_threads()

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

            weight = resolve_train_weight(job.base_model)
            job.log_tail = f"使用权重 {weight}"
            db.session.commit()
            model = YOLO(weight)
            model.add_callback("on_fit_epoch_end", on_fit_epoch)
            train_kw = dict(
                data=str(yaml_path),
                epochs=job.epochs,
                batch=job.batch,
                imgsz=job.imgsz,
                device=job.device,
                project=str(out_dir),
                name="exp",
                exist_ok=True,
                verbose=False,
                plots=True,
            )
            if cpu_safe:
                train_kw.update(
                    workers=max(0, Config.CPU_WORKERS),
                    cache=False,
                    mosaic=0.0,
                )
            model.train(**train_kw)
            best = out_dir / "exp" / "weights" / "best.pt"
            job = db.session.get(TrainJob, job_id)
            if best.exists():
                folder = job.folder or f"train-{job.id}"
                key = f"train-{folder}"
                dest_dir = trained_model_dir(folder)
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
                        description=f"由训练任务 {job.job_name} 产出",
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
        finally:
            if Config.CPU_SAFE:
                _set_windows_priority(False)
            if use_lock:
                _train_lock.release()

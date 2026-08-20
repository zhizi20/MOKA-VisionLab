"""导入 Ultralytics Platform 导出的 .ndjson：按 URL 拉图并写入 YOLO 标注。"""
from __future__ import annotations

import json
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

import_jobs: dict[str, dict] = {}
import_jobs_lock = threading.Lock()
latest_dataset_jobs: dict[int, str] = {}

FAILED_FILE = "failed.json"
SOURCE_FILE = "source.ndjson"


def parse_ndjson(path: Path) -> tuple[dict, list[dict]]:
    meta = {"name": path.stem, "class_names": {}, "description": ""}
    images: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            rtype = rec.get("type")
            if rtype == "dataset":
                meta = rec
            elif rtype == "image":
                images.append(rec)
    return meta, images


def class_name_list(meta: dict) -> list[str]:
    raw = meta.get("class_names") or {}
    if isinstance(raw, dict):
        items = sorted(raw.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else str(kv[0]))
        return [str(v) for _, v in items]
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return []


def image_filename(rec: dict) -> str:
    return Path(rec.get("file") or "image.jpg").name


def dedupe_images(images: list[dict]) -> list[dict]:
    """同一文件名可能同时出现在 train/test；只保留一份，优先有标注、再优先 train。"""
    rank = {"train": 3, "val": 2, "test": 1}
    best: dict[str, tuple[tuple[int, int], dict]] = {}
    for rec in images:
        name = image_filename(rec)
        boxes = ((rec.get("annotations") or {}).get("boxes")) or []
        split = (rec.get("split") or "train").lower()
        score = (1 if boxes else 0, rank.get(split, 0))
        prev = best.get(name)
        if prev is None or score > prev[0]:
            best[name] = (score, rec)
    return [item[1] for item in best.values()]


def raw_image_path(ds_dir: Path, rec: dict) -> Path:
    return ds_dir / "raw" / "images" / image_filename(rec)


def image_ok(path: Path) -> bool:
    return path.is_file() and path.stat().st_size >= 32


def list_missing(ds_dir: Path, images: list[dict]) -> list[dict]:
    return [rec for rec in images if not image_ok(raw_image_path(ds_dir, rec))]


def missing_failures(ds_dir: Path) -> list[dict]:
    src = find_source_ndjson(ds_dir)
    if src is None:
        return []
    try:
        _, images = parse_ndjson(src)
        images = dedupe_images(images)
    except Exception:  # noqa: BLE001
        return failed
    missing = list_missing(ds_dir, images)
    if not missing:
        return []
    err_map = {item.get("file"): item for item in failed}
    rows = []
    for rec in missing:
        name = image_filename(rec)
        item = err_map.get(name) or {
            "file": name,
            "url": rec.get("url") or "",
            "split": rec.get("split") or "train",
            "annotations": rec.get("annotations") or {},
            "error": "文件缺失，待重试",
        }
        rows.append(item)
    return rows


def load_failed(ds_dir: Path) -> list[dict]:
    path = ds_dir / FAILED_FILE
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def save_failed(ds_dir: Path, failures: list[dict]):
    path = ds_dir / FAILED_FILE
    if failures:
        path.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    elif path.exists():
        path.unlink()


def find_source_ndjson(ds_dir: Path) -> Path | None:
    """只使用该数据集目录内的 source.ndjson，绝不扫描其它数据集。"""
    src = ds_dir / SOURCE_FILE
    return src if src.is_file() else None


def bind_dataset_job(dataset_id: int, job_id: str):
    latest_dataset_jobs[dataset_id] = job_id


def snapshot_job(dataset_id: int) -> dict | None:
    jid = latest_dataset_jobs.get(dataset_id)
    if not jid:
        return None
    with import_jobs_lock:
        job = import_jobs.get(jid)
        if not job:
            return None
        status = job.get("status")
        if status not in {"running", "paused"}:
            return None
        return {
            "jobId": jid,
            "status": status,
            "progress": int(job.get("progress") or 0),
            "processed": int(job.get("processed") or 0),
            "total": int(job.get("total") or 0),
            "failed": int(job.get("failed") or 0),
            "paused": bool(job.get("paused")),
        }


def set_paused(job_id: str, paused: bool) -> bool:
    with import_jobs_lock:
        job = import_jobs.get(job_id)
        if not job or job.get("status") not in {"running", "paused"}:
            return False
        job["paused"] = paused
        job["status"] = "paused" if paused else "running"
        return True


def wait_if_paused(job_id: str):
    while True:
        with import_jobs_lock:
            job = import_jobs.get(job_id)
            if job is None or not job.get("paused"):
                return
        time.sleep(0.3)


def _err_text(exc: BaseException) -> str:
    if isinstance(exc, requests.Timeout):
        return "网络超时"
    if isinstance(exc, requests.ConnectionError):
        return "网络连接失败"
    if isinstance(exc, requests.HTTPError):
        code = exc.response.status_code if exc.response is not None else "?"
        return f"HTTP {code}"
    text = str(exc).strip() or exc.__class__.__name__
    return text[:240]


def _write_yolo_txt(path: Path, boxes: list):
    lines = []
    for box in boxes:
        if not isinstance(box, (list, tuple)) or len(box) < 5:
            continue
        cls, cx, cy, w, h = box[:5]
        lines.append(f"{int(cls)} {float(cx):.6f} {float(cy):.6f} {float(w):.6f} {float(h):.6f}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _download(url: str, dest: Path, retries: int = 3):
    dest.parent.mkdir(parents=True, exist_ok=True)
    last: BaseException | None = None
    for attempt in range(1, retries + 1):
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            resp = requests.get(
                url,
                timeout=90,
                stream=True,
                headers={"User-Agent": "MOKA-VisionLab/0.1"},
            )
            resp.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
            if tmp.stat().st_size < 32:
                tmp.unlink(missing_ok=True)
                raise RuntimeError("下载文件过小")
            tmp.replace(dest)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            tmp.unlink(missing_ok=True)
            dest.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(min(2 * attempt, 6))
    raise RuntimeError(_err_text(last or RuntimeError("下载失败")))


def _write_data_yaml(yolo_dir: Path, names: list[str], has_test: bool):
    names_txt = ", ".join(repr(n) for n in names)
    text = (
        f"path: {yolo_dir.as_posix()}\n"
        f"train: images/train\n"
        f"val: images/val\n"
    )
    if has_test:
        text += "test: images/test\n"
    text += f"nc: {len(names)}\nnames: [{names_txt}]\n"
    (yolo_dir / "data.yaml").write_text(text, encoding="utf-8")


def _place_labeled(ds_dir: Path, dest: Path, rec: dict):
    boxes = ((rec.get("annotations") or {}).get("boxes")) or []
    if not boxes:
        return
    split = (rec.get("split") or "train").lower()
    if split not in {"train", "val", "test"}:
        split = "train"
    stem = dest.stem
    yolo_dir = ds_dir / "yolo"
    _write_yolo_txt(ds_dir / "raw" / "labels" / f"{stem}.txt", boxes)
    (yolo_dir / "images" / split).mkdir(parents=True, exist_ok=True)
    (yolo_dir / "labels" / split).mkdir(parents=True, exist_ok=True)
    shutil.copy2(dest, yolo_dir / "images" / split / dest.name)
    _write_yolo_txt(yolo_dir / "labels" / split / f"{stem}.txt", boxes)


def _finalize_yolo(ds_dir: Path, names: list[str]) -> dict:
    yolo_dir = ds_dir / "yolo"
    train_n = len(list((yolo_dir / "labels" / "train").glob("*.txt")))
    val_n = len(list((yolo_dir / "labels" / "val").glob("*.txt")))
    test_n = len(list((yolo_dir / "labels" / "test").glob("*.txt")))
    if val_n == 0 and test_n > 0:
        for src_kind in ("images", "labels"):
            src = yolo_dir / src_kind / "test"
            dst = yolo_dir / src_kind / "val"
            dst.mkdir(parents=True, exist_ok=True)
            for p in src.iterdir():
                target = dst / p.name
                if not target.exists():
                    shutil.copy2(p, target)
        val_n = test_n
    has_test = test_n > 0
    yaml_ok = train_n >= 1 and val_n >= 1 and bool(names)
    if yaml_ok:
        _write_data_yaml(yolo_dir, names, has_test)
    return {"train": train_n, "val": val_n, "test": test_n, "yamlOk": yaml_ok}


def _update_job(job_id: str, **fields):
    with import_jobs_lock:
        job = import_jobs.get(job_id)
        if job:
            job.update(fields)


def run_ndjson_import(job_id: str, ds_dir: Path, names: list[str], images: list[dict], retries: int = 3):
    raw_img = ds_dir / "raw" / "images"
    raw_lbl = ds_dir / "raw" / "labels"
    yolo_dir = ds_dir / "yolo"
    raw_img.mkdir(parents=True, exist_ok=True)
    raw_lbl.mkdir(parents=True, exist_ok=True)
    for split in ("train", "val", "test"):
        (yolo_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (yolo_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    images = dedupe_images(images)
    pending = list_missing(ds_dir, images)
    total_all = len(images)
    already = total_all - len(pending)
    batch = pending
    total = len(batch)
    ok = 0
    failed = 0
    attempted = 0
    failures: list[dict] = []

    _update_job(
        job_id,
        total=total_all,
        skipped=already,
        processed=already,
        failed=0,
        attempted=0,
        batchTotal=total,
        paused=False,
        progress=int(already * 100 / max(total_all, 1)) if not batch else 0,
        failures=[],
    )

    def one(rec: dict):
        wait_if_paused(job_id)
        dest = raw_image_path(ds_dir, rec)
        if not image_ok(dest):
            url = rec.get("url") or ""
            if not url:
                raise RuntimeError("缺少下载地址")
            _download(url, dest, retries=retries)
        wait_if_paused(job_id)
        _place_labeled(ds_dir, dest, rec)
        return image_filename(rec)

    if batch:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(one, rec): rec for rec in batch}
            for fut in as_completed(futures):
                rec = futures[fut]
                attempted += 1
                try:
                    fut.result()
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    failures.append({
                        "file": image_filename(rec),
                        "url": rec.get("url") or "",
                        "split": rec.get("split") or "train",
                        "annotations": rec.get("annotations") or {},
                        "error": _err_text(exc),
                    })
                _update_job(
                    job_id,
                    processed=already + ok,
                    failed=failed,
                    attempted=attempted,
                    batchTotal=total,
                    progress=int((already + ok + failed) * 100 / max(total_all, 1)),
                    failures=failures,
                )

    save_failed(ds_dir, failures)
    stats = _finalize_yolo(ds_dir, names)
    missing = list_missing(ds_dir, images)
    complete = len(missing) == 0
    ready = bool(stats["yamlOk"] and complete)
    _update_job(
        job_id,
        processed=already + ok,
        failed=len(failures),
        failures=failures,
        trainCount=stats["train"],
        valCount=stats["val"],
        testCount=stats["test"],
        progress=100,
        ready=ready,
        complete=complete,
    )
    return {
        "train": stats["train"],
        "val": stats["val"],
        "test": stats["test"],
        "failed": len(failures),
        "ok": already + ok,
        "ready": ready,
        "complete": complete,
        "failures": failures,
    }

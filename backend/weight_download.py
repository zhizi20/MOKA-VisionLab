"""下载 Ultralytics YOLO 权重。直连 GitHub 在国内常超时，会自动换镜像。"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from urllib.parse import urlparse

import requests

download_jobs: dict[str, dict] = {}
download_jobs_lock = threading.Lock()

_ASSET_TAGS = ("v8.4.0", "v8.3.0", "v8.2.0")
_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MOKA-VisionLab/0.1",
    "Accept": "*/*",
}
_CONNECT_TIMEOUT = 8
_READ_TIMEOUT = 180
_MIN_WEIGHT_BYTES = 100 * 1024
_DEFAULT_MIRRORS = (
    "https://ghfast.top/",
    "https://ghproxy.net/",
    "https://gh-proxy.com/",
    "https://mirror.ghproxy.com/",
    "https://gh.llkk.cc/",
)


def weight_url(filename: str, tag: str | None = None) -> str:
    if tag is None:
        if filename.startswith("yolo26"):
            tag = "v8.4.0"
        elif filename.startswith("yolo12"):
            tag = "v8.4.0"
        elif filename.startswith("yolo11"):
            tag = "v8.3.0"
        else:
            tag = "v8.2.0"
    return f"https://github.com/ultralytics/assets/releases/download/{tag}/{filename}"


def _mirrors() -> list[str]:
    raw = os.getenv("DETECTLAB_GH_MIRRORS", "")
    if raw.strip():
        return [x.strip() for x in raw.split(",") if x.strip()]
    return list(_DEFAULT_MIRRORS)


def _hf_endpoint() -> str:
    return (os.getenv("DETECTLAB_HF_ENDPOINT") or "https://hf-mirror.com").rstrip("/")


def _hf_family(filename: str) -> str | None:
    if filename.startswith("yolo26"):
        return "YOLO26"
    if filename.startswith("yolo12"):
        return "YOLO12"
    if filename.startswith("yolo11"):
        return "YOLO11"
    if filename.startswith("yolov8"):
        return "YOLOv8"
    return None


def _candidate_urls(filename: str) -> list[str]:
    urls: list[str] = []
    family = _hf_family(filename)
    if family:
        hf = _hf_endpoint()
        urls.append(f"{hf}/Ultralytics/{family}/resolve/main/{filename}")
        if "hf-mirror.com" in hf:
            urls.append(f"https://huggingface.co/Ultralytics/{family}/resolve/main/{filename}")

    origin = weight_url(filename)
    for mirror in _mirrors():
        urls.append(mirror.rstrip("/") + "/" + origin)
    urls.append(origin.replace("https://github.com/", "https://kkgithub.com/"))
    urls.append(origin)

    for tag in _ASSET_TAGS:
        tagged = weight_url(filename, tag)
        if tagged == origin:
            continue
        for mirror in _mirrors()[:2]:
            urls.append(mirror.rstrip("/") + "/" + tagged)
        urls.append(tagged)

    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def _update(job_id: str, **fields):
    with download_jobs_lock:
        job = download_jobs.get(job_id)
        if job:
            job.update(fields)


def find_existing_weight(filename: str, search_root: Path | None = None) -> Path | None:
    name = Path(filename).name
    if search_root is None:
        return None
    for candidate in (
        search_root / "builtin" / name,
        search_root / Path(name).stem / name,
        search_root / name,
    ):
        if candidate.is_file() and candidate.stat().st_size > _MIN_WEIGHT_BYTES:
            return candidate
    if search_root.exists():
        for path in search_root.rglob(name):
            if path.is_file() and path.stat().st_size > _MIN_WEIGHT_BYTES:
                return path
    return None


def download_weight(job_id: str, filename: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_error: Exception | None = None
    failed_hosts: set[str] = set()
    tried: list[str] = []
    try:
        for url in _candidate_urls(filename):
            host = urlparse(url).netloc
            if host in failed_hosts:
                continue
            tried.append(url)
            _update(job_id, status="running", url=url, progress=0, error=None)
            try:
                with requests.get(
                    url,
                    stream=True,
                    timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
                    allow_redirects=True,
                    headers=_UA,
                ) as resp:
                    if resp.status_code == 404:
                        last_error = RuntimeError(f"资源不存在：{url}")
                        continue
                    resp.raise_for_status()
                    total = int(resp.headers.get("Content-Length") or 0)
                    _update(job_id, total=total, url=str(resp.url))
                    done = 0
                    with tmp.open("wb") as f:
                        for chunk in resp.iter_content(chunk_size=1024 * 256):
                            if not chunk:
                                continue
                            f.write(chunk)
                            done += len(chunk)
                            pct = int(done * 100 / total) if total else min(99, done // (1024 * 1024))
                            _update(job_id, downloaded=done, progress=min(99, pct))
                if not tmp.exists() or tmp.stat().st_size < _MIN_WEIGHT_BYTES:
                    tmp.unlink(missing_ok=True)
                    last_error = RuntimeError("下载文件过小，可能不是有效权重")
                    continue
                tmp.replace(dest)
                size = dest.stat().st_size
                _update(job_id, status="done", progress=100, downloaded=size, total=size)
                return
            except requests.exceptions.ConnectTimeout as exc:
                tmp.unlink(missing_ok=True)
                failed_hosts.add(host)
                last_error = exc
                continue
            except requests.exceptions.ConnectionError as exc:
                tmp.unlink(missing_ok=True)
                failed_hosts.add(host)
                last_error = exc
                continue
            except requests.RequestException as exc:
                tmp.unlink(missing_ok=True)
                last_error = exc
                continue
        hint = (
            f"无法下载 {filename}。本机访问 GitHub 超时，已尝试 HuggingFace 镜像和 GitHub 代理。"
            f"请检查网络，或在模型管理里手动上传 .pt。最后错误：{last_error}"
        )
        if tried:
            hint += f" 已尝试 {len(tried)} 个地址。"
        raise RuntimeError(hint)
    except Exception as exc:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        _update(job_id, status="failed", error=str(exc))
        raise

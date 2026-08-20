import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "ai-detectlab-dev-secret-change-me")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(seconds=int(os.getenv("JWT_EXPIRES_SECONDS", "86400")))
    JWT_TOKEN_LOCATION = ["headers"]

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{(BASE_DIR / 'app.db').as_posix()}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"check_same_thread": False}}
    JSON_AS_ASCII = False
    MAX_CONTENT_LENGTH = _env_int("MAX_CONTENT_LENGTH", 4 * 1024 * 1024 * 1024)

    UPLOAD_FOLDER = BASE_DIR / "uploads"
    DATASET_FOLDER = UPLOAD_FOLDER / "datasets"
    TRAINING_FOLDER = UPLOAD_FOLDER / "training"
    MODEL_FOLDER = UPLOAD_FOLDER / "models"
    VIDEO_FOLDER = UPLOAD_FOLDER / "videos" / "source"
    OUTPUT_FOLDER = UPLOAD_FOLDER / "videos" / "results"
    TMP_FOLDER = UPLOAD_FOLDER / "tmp"

    MODEL_ALLOWED_EXT = {".pt"}
    VIDEO_ALLOWED_EXT = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    IMAGE_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

    # 本机测试默认开启 CPU 保护。更好的机器可在 backend/.env 设 DETECTLAB_CPU_SAFE=0。
    CPU_SAFE = _env_flag("DETECTLAB_CPU_SAFE", True)
    CPU_MAX_BATCH = _env_int("DETECTLAB_CPU_MAX_BATCH", 4)
    CPU_MAX_IMGSZ = _env_int("DETECTLAB_CPU_MAX_IMGSZ", 640)
    CPU_TORCH_THREADS = _env_int("DETECTLAB_CPU_THREADS", 4)
    CPU_WORKERS = _env_int("DETECTLAB_CPU_WORKERS", 0)
    ALLOW_PARALLEL_TRAIN = _env_flag("DETECTLAB_ALLOW_PARALLEL_TRAIN", False)


def ensure_dirs():
    for p in (
        Config.UPLOAD_FOLDER,
        Config.MODEL_FOLDER,
        Config.MODEL_FOLDER / "builtin",
        Config.MODEL_FOLDER / "custom",
        Config.MODEL_FOLDER / "trained",
        Config.DATASET_FOLDER,
        Config.VIDEO_FOLDER,
        Config.OUTPUT_FOLDER,
        Config.TRAINING_FOLDER,
        Config.TMP_FOLDER,
    ):
        p.mkdir(parents=True, exist_ok=True)

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


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
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024

    UPLOAD_FOLDER = BASE_DIR / "uploads"
    MODEL_FOLDER = UPLOAD_FOLDER / "models"
    DATASET_FOLDER = UPLOAD_FOLDER / "datasets"
    VIDEO_FOLDER = UPLOAD_FOLDER / "videos"
    OUTPUT_FOLDER = UPLOAD_FOLDER / "outputs"
    TRAINING_FOLDER = UPLOAD_FOLDER / "training"

    MODEL_ALLOWED_EXT = {".pt"}
    VIDEO_ALLOWED_EXT = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    IMAGE_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def ensure_dirs():
    for p in (
        Config.UPLOAD_FOLDER,
        Config.MODEL_FOLDER,
        Config.DATASET_FOLDER,
        Config.VIDEO_FOLDER,
        Config.OUTPUT_FOLDER,
        Config.TRAINING_FOLDER,
    ):
        p.mkdir(parents=True, exist_ok=True)

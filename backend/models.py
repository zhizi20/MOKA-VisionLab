from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


def _now():
    return datetime.now()


class User(db.Model):
    __tablename__ = "sys_user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    nickname = db.Column(db.String(64), default="管理员")
    create_time = db.Column(db.DateTime, default=_now)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class DetectModel(db.Model):
    __tablename__ = "detect_model"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, index=True)
    model_key = db.Column(db.String(128), unique=True, nullable=False, index=True)
    version = db.Column(db.String(32), default="1.0")
    category = db.Column(db.String(64), default="目标检测")
    library = db.Column(db.String(32), default="ultralytics")
    file_path = db.Column(db.String(500))
    file_size = db.Column(db.Integer, default=0)
    description = db.Column(db.Text, default="")
    status = db.Column(db.String(8), default="0")  # 0 启用 1 停用
    source = db.Column(db.String(32), default="upload")  # upload / train / builtin
    create_time = db.Column(db.DateTime, default=_now)


class Dataset(db.Model):
    __tablename__ = "dataset"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    class_names = db.Column(db.String(500), default="")
    status = db.Column(db.String(16), default="raw")  # raw / ready
    train_count = db.Column(db.Integer, default=0)
    val_count = db.Column(db.Integer, default=0)
    split_ratio = db.Column(db.Float, default=0.8)
    description = db.Column(db.Text, default="")
    folder = db.Column(db.String(160), default="")
    create_time = db.Column(db.DateTime, default=_now)


class TrainJob(db.Model):
    __tablename__ = "train_job"

    id = db.Column(db.Integer, primary_key=True)
    job_name = db.Column(db.String(128), nullable=False)
    dataset_id = db.Column(db.Integer, index=True, nullable=False)
    base_model = db.Column(db.String(64), default="yolo11n.pt")
    epochs = db.Column(db.Integer, default=20)
    batch = db.Column(db.Integer, default=4)
    imgsz = db.Column(db.Integer, default=640)
    device = db.Column(db.String(16), default="cpu")
    status = db.Column(db.String(16), default="pending")
    progress = db.Column(db.Integer, default=0)
    current_epoch = db.Column(db.Integer, default=0)
    metrics = db.Column(db.Text, default="")
    log_tail = db.Column(db.Text, default="")
    error = db.Column(db.Text, default="")
    result_model_id = db.Column(db.Integer)
    folder = db.Column(db.String(160), default="")
    create_time = db.Column(db.DateTime, default=_now)

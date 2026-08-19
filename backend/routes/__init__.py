from routes.auth import auth_bp
from routes.datasets import datasets_bp
from routes.detect import detect_bp
from routes.models import models_bp
from routes.training import jobs_bp

all_blueprints = [auth_bp, models_bp, detect_bp, datasets_bp, jobs_bp]

from flask import Blueprint, request
from flask_jwt_extended import create_access_token

from models import User
from security import current_user, login_required
from utils import fail, ok

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return fail("用户名和密码不能为空")
    user = User.query.filter_by(username=username).first()
    if user is None or not user.check_password(password):
        return fail("用户名或密码错误", 401)
    token = create_access_token(identity=str(user.id))
    return ok({"token": token}, "登录成功")


@auth_bp.get("/info")
@login_required
def info():
    user = current_user()
    return ok({"id": user.id, "username": user.username, "nickname": user.nickname})

from functools import wraps

from flask import g, jsonify
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from extensions import db
from models import User


def current_user():
    if "current_user" not in g:
        uid = get_jwt_identity()
        g.current_user = db.session.get(User, int(uid)) if uid is not None else None
    return g.current_user


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        if current_user() is None:
            return jsonify(code=401, message="用户不存在或已禁用", data=None), 401
        return fn(*args, **kwargs)

    return wrapper

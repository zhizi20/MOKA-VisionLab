from models import User
from extensions import db


def init_seed():
    if User.query.count() == 0:
        admin = User(username="admin", nickname="管理员")
        admin.set_password("admin123")
        db.session.add(admin)
        db.session.commit()

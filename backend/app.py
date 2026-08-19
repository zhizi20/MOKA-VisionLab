from flask import Flask, jsonify

from config import Config, ensure_dirs
from extensions import cors, db, jwt
from routes import all_blueprints
from seed import init_seed


def create_app():
    ensure_dirs()
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": "*"}})
    jwt.init_app(app)

    for bp in all_blueprints:
        app.register_blueprint(bp)

    @app.get("/api/health")
    def health():
        return jsonify(code=0, message="ok")

    @jwt.unauthorized_loader
    def _missing_token(_reason):
        return jsonify(code=401, message="缺少或无效的令牌", data=None), 401

    @jwt.invalid_token_loader
    def _invalid_token(_reason):
        return jsonify(code=401, message="令牌无效", data=None), 401

    @jwt.expired_token_loader
    def _expired_token(_header, _payload):
        return jsonify(code=401, message="登录已过期，请重新登录", data=None), 401

    with app.app_context():
        import models  # noqa: F401

        db.create_all()
        init_seed()

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True, threaded=True, use_reloader=False)

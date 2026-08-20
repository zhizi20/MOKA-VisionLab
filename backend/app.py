from flask import Flask, jsonify, make_response, request

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

    @app.get("/")
    def index():
        host = (request.host or "127.0.0.1").split(":")[0] or "127.0.0.1"
        ui = f"http://{host}:5174"
        html = f"""<!doctype html>
<meta charset="utf-8">
<title>MOKA-VisionLab API</title>
<body style="font-family:sans-serif;max-width:640px;margin:48px auto;line-height:1.7">
<h1>这是后端 API（8000 端口），不是网页界面</h1>
<p>请打开前端：</p>
<ul>
  <li><a href="{ui}">{ui}</a></li>
  <li>登录页 <a href="{ui}/login">{ui}/login</a>（默认 admin / admin123）</li>
  <li>健康检查 <a href="/api/health">/api/health</a></li>
</ul>
<p>浏览器访问本地址时，旧日志里的 404 只是因为这里以前没有首页路由。</p>
</body>"""
        resp = make_response(html)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        return resp

    @app.get("/favicon.ico")
    def favicon():
        return ("", 204)

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
        from storage import ensure_schema, migrate_uploads
        from routes.training import mark_interrupted_jobs

        ensure_schema()
        migrate_uploads()
        mark_interrupted_jobs()

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True, threaded=True, use_reloader=False)

from __future__ import annotations

from dotenv import find_dotenv, load_dotenv
from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

# リポジトリ root の .env → .env.local の順に読み込む（.env.local が優先）。
# 本番（Render 等）では環境変数が直接注入されるので override=False で上書きしない。
load_dotenv(find_dotenv(".env", usecwd=True), override=False)
load_dotenv(find_dotenv(".env.local", usecwd=True), override=True)


def create_app() -> Flask:
    """Routeful バックエンドの Flask アプリを生成する。

    Render の start command (`gunicorn 'src.app:create_app()'`) と
    `.venv/bin/python -m flask --app src.app:create_app run` の両方から参照される。
    """
    app = Flask(__name__)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "service": "routeful-api"}

    # Blueprints
    from .routes.evidence_routes import bp as evidence_bp
    app.register_blueprint(evidence_bp)

    # HTTPException（404 / 405 / 413 など）は Flask 標準のステータス・メッセージを維持。
    # これを先に分岐しないと下の Exception ハンドラが全部 500 に潰してしまう。
    @app.errorhandler(HTTPException)
    def handle_http_exception(e: HTTPException):
        return jsonify({"error": e.description}), e.code or 500

    # 最後の砦: HTTPException 以外の想定外例外を 500 に畳み込み、スタックはログに残す
    @app.errorhandler(Exception)
    def handle_unexpected_error(e):
        app.logger.exception(f"unhandled error: {e}")
        return jsonify({"error": "internal server error"}), 500

    return app

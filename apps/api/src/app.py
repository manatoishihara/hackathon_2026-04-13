from __future__ import annotations

import os

from dotenv import find_dotenv, load_dotenv
from flask import Flask, jsonify
from flask_compress import Compress
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

# リポジトリ root の .env → .env.local の順に読み込む（.env.local が優先）。
# 本番（Render 等）では環境変数が直接注入されるので override=False で上書きしない。
load_dotenv(find_dotenv(".env", usecwd=True), override=False)
load_dotenv(find_dotenv(".env.local", usecwd=True), override=True)


_DEFAULT_CORS_ORIGINS = ["http://localhost:3000"]


def _resolve_cors_origins() -> list[str]:
    """`CORS_ALLOWED_ORIGINS`(カンマ区切り) を読む。未設定時はローカル開発用デフォルト。

    本番（Render）では Vercel 本番ドメインを `CORS_ALLOWED_ORIGINS` に設定する。
    """
    raw = os.environ.get("CORS_ALLOWED_ORIGINS")
    if not raw:
        return list(_DEFAULT_CORS_ORIGINS)
    return [o.strip() for o in raw.split(",") if o.strip()]


def create_app() -> Flask:
    """Routeful バックエンドの Flask アプリを生成する。

    Render の start command (`gunicorn 'src.app:create_app()'`) と
    `.venv/bin/python -m flask --app src.app:create_app run` の両方から参照される。
    """
    app = Flask(__name__)

    # gzip 圧縮: 1KB 以上の JSON レスポンスに自動適用（⑤ 軽量化）
    app.config["COMPRESS_ALGORITHM"] = "gzip"
    app.config["COMPRESS_MIN_SIZE"] = 1024
    Compress(app)

    # レート制限（⑭ フォールバック設計 / 公開エンドポイント保護）
    from .extensions import limiter
    limiter.init_app(app)

    # CORS: フロント (Vercel) → バック (Render) は cross-origin。`Authorization` ヘッダ
    # を送るためプリフライト OPTIONS が走る。allowlist 指定で credentials は使わない。
    origins = _resolve_cors_origins()
    CORS(
        app,
        resources={r"/*": {"origins": origins}},
        allow_headers=["Authorization", "Content-Type"],
        methods=["GET", "POST", "OPTIONS"],
        max_age=600,
    )

    # 巨大ペイロード DoS の一次防衛。Flask 既定値は None なので直接代入で確実にかける
    # （setdefault では既定値 None を上書きしない）。transit_matrix 最大 200 件 +
    # overhead を余裕をもってカバーする 256KB。
    app.config["MAX_CONTENT_LENGTH"] = 256 * 1024

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "service": "routeful-api"}

    # Blueprints
    from .routes.evidence_routes import bp as evidence_bp
    from .routes.plan_routes import bp as plan_bp
    from .routes.share_routes import bp as share_bp
    app.register_blueprint(evidence_bp)
    app.register_blueprint(plan_bp)
    app.register_blueprint(share_bp)

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

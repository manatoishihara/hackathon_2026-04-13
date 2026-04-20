from __future__ import annotations

from dotenv import find_dotenv, load_dotenv
from flask import Flask

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

    return app

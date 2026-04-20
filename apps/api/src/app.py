from flask import Flask


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

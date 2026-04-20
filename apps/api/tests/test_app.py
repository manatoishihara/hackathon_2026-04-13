from src.app import create_app


def test_healthz_returns_ok():
    app = create_app()
    client = app.test_client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "service": "routeful-api"}

from fastapi.testclient import TestClient

from app.infrastructure.config import AppConfig
from app.main import create_app


def test_built_frontend_and_spa_routes_share_the_api_origin(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><h1>AgentCity built client</h1>", encoding="utf-8")
    (dist / "assets" / "client.js").write_text("console.log('built client')", encoding="utf-8")
    (tmp_path / "private.txt").write_text("never public", encoding="utf-8")
    app = create_app(AppConfig(data_dir=tmp_path / "data", frontend_dist=dist))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        assert "AgentCity built client" in client.get("/").text
        assert "AgentCity built client" in client.get("/simulations/a-saved-world").text
        assert "console.log" in client.get("/assets/client.js").text
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get("/api/v1/missing").json()["error"]["code"] == "NOT_FOUND"
        assert client.get("/health/ready").json()["status"] == "ok"
        assert client.get("/api/v1/capabilities").json()["data"]["contract_version"] == "1.0.0"
        assert "never public" not in client.get("/%2e%2e/private.txt").text
    assert app.openapi() == create_app().openapi()

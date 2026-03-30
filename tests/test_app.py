from fastapi.testclient import TestClient

from sync115pan.app import app


def test_dashboard_renders() -> None:
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "115 云盘同步控制台" in response.text

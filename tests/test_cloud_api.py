from fastapi.testclient import TestClient

from sync115pan import app as app_module


def test_cloud_directories_returns_string_ids(monkeypatch) -> None:
    class DummyCloud:
        def configured(self) -> bool:
            return True

        def list_children(self, parent_id):
            assert parent_id == "0"
            return {"空文件夹": 3396240814710456321}, set()

    monkeypatch.setattr(app_module, "make_cloud_service", lambda: DummyCloud())
    monkeypatch.setattr(app_module.runtime, "start", lambda: None)
    monkeypatch.setattr(app_module.runtime, "stop", lambda: None)

    with TestClient(app_module.app) as client:
        response = client.get("/api/cloud/directories?parent_id=0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["directories"][0]["id"] == "3396240814710456321"

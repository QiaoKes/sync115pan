from fastapi.testclient import TestClient

from sync115pan import app as app_module


def test_cloud_directories_returns_string_ids(monkeypatch) -> None:
    class DummyEntry:
        def __init__(self, remote_id: int, name: str, is_dir: bool = True) -> None:
            self.remote_id = remote_id
            self.name = name
            self.is_dir = is_dir

    class DummyCloud:
        def configured(self) -> bool:
            return True

        def list_directory(self, parent_id):
            assert parent_id == "0"
            return [DummyEntry(3396240814710456321, "空文件夹")]

    monkeypatch.setattr(app_module, "make_cloud_service", lambda: DummyCloud())
    monkeypatch.setattr(app_module.runtime, "start", lambda: None)
    monkeypatch.setattr(app_module.runtime, "stop", lambda: None)

    with TestClient(app_module.app) as client:
        response = client.get("/api/cloud/directories?parent_id=0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["directories"][0]["id"] == "3396240814710456321"

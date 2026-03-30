from pathlib import Path

from sync115pan.config import AppPaths
from sync115pan.store import AppState
from sync115pan.syncer import SyncService


class DummyCloud:
    def export_tree_debug(self, root_id):
        assert root_id == "1"
        return [], []

    def export_tree(self, root_id):
        assert root_id == "1"
        return []

    def attempt_instant_upload(self, local_path: Path, parent_id: int, filename: str):
        assert parent_id == 1
        return {
            "filesize": local_path.stat().st_size,
            "filesha1": "sha1",
            "response": {"reuse": True},
        }


def test_full_sync_uses_export_and_uploads_missing_file(tmp_path: Path) -> None:
    local_file = tmp_path / "demo.txt"
    local_file.write_text("hello", encoding="utf-8")

    state = AppState(
        tmp_path / "config.json",
        tmp_path / "retry_state.json",
        tmp_path / "app.log",
    )
    state.update_config(
        {
            "auth_value": "UID=1; CID=2",
            "local_path": str(tmp_path),
            "cloud_root_id": "1",
            "cloud_path": "根目录",
        }
    )
    app_paths = AppPaths(
        root=tmp_path,
        data_dir=tmp_path,
        config_path=tmp_path / "config.json",
        retry_state_path=tmp_path / "retry_state.json",
        log_path=tmp_path / "app.log",
        cookies_path=tmp_path / "115-cookies.txt",
    )
    service = SyncService(state, app_paths)
    service._make_cloud = lambda config: DummyCloud()  # type: ignore[method-assign]

    service._run_full_sync()

    logs = state.list_logs()
    assert any("云端目录树已通过导出接口获取" in log["message"] for log in logs)
    assert any("秒传成功，已完成同步：demo.txt" in log["message"] for log in logs)

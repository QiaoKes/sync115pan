from pathlib import Path

from sync115pan.config import AppPaths
from sync115pan.store import AppState
from sync115pan.syncer import SyncService


class DummyCloud:
    def export_relative_paths(self, root_id, cloud_root_path, include_raw=False):
        assert root_id == 1
        assert cloud_root_path == "根目录"
        if include_raw:
            return ["/"], set()
        return set()

    def ensure_remote_dir(self, root_id, relative_dir, dir_cache=None):
        assert root_id == 1
        if dir_cache is not None:
            dir_cache.setdefault("", 1)
        return 1, False

    def list_children(self, parent_id):
        assert parent_id == 1
        return {}, set()

    def attempt_instant_upload(self, local_path: Path, parent_id: int, filename: str):
        assert parent_id == 1
        return {
            "filesize": local_path.stat().st_size,
            "filesha1": "sha1",
            "response": {"reuse": True},
        }


def make_service(tmp_path: Path) -> tuple[AppState, SyncService]:
    local_root = tmp_path / "local"
    local_root.mkdir(exist_ok=True)
    state = AppState(
        tmp_path / "config.json",
        tmp_path / "retry_state.json",
        tmp_path / "app.log",
    )
    state.update_config(
        {
            "auth_value": "UID=1; CID=2",
            "local_path": str(local_root),
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
    return state, SyncService(state, app_paths)


def test_full_sync_uses_export_and_uploads_missing_file(tmp_path: Path) -> None:
    local_file = tmp_path / "local" / "demo.txt"
    local_file.parent.mkdir(exist_ok=True)
    local_file.write_text("hello", encoding="utf-8")

    state, service = make_service(tmp_path)
    service._make_cloud = lambda config: DummyCloud()  # type: ignore[method-assign]

    service._run_full_sync()

    logs = state.list_logs()
    assert any("全量检查：" in log["message"] for log in logs)
    assert any("文件已同步：方式=秒传" in log["message"] and "demo.txt" in log["message"] for log in logs)


def test_full_sync_skips_existing_remote_directory(tmp_path: Path) -> None:
    local_root = tmp_path / "local"
    local_root.mkdir()
    (local_root / "目录A").mkdir()

    class ExistingDirCloud(DummyCloud):
        def export_relative_paths(self, root_id, cloud_root_path, include_raw=False):
            assert root_id == 1
            assert cloud_root_path == "根目录"
            result = {""}
            if include_raw:
                return ["/"], result
            return result

        def ensure_remote_dir(self, root_id, relative_dir, dir_cache=None):
            assert root_id == 1
            assert relative_dir == "目录A"
            if dir_cache is not None:
                dir_cache[relative_dir] = 100
            return 100, False

    state, service = make_service(tmp_path)
    service._make_cloud = lambda config: ExistingDirCloud()  # type: ignore[method-assign]

    service._run_full_sync()

    logs = state.list_logs()
    assert any("云端目录已存在，跳过创建：/目录A" in log["message"] for log in logs)

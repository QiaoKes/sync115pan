from datetime import UTC, datetime, timedelta
from pathlib import Path

from sync115pan.config import AppPaths
from sync115pan.runtime import RuntimeSupervisor
from sync115pan.store import AppState


class DummySyncService:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def request_recheck(self, scope: str) -> None:
        self.scopes.append(scope)

    def snapshot(self):
        return {
            "status": "idle",
            "current_job": "",
            "last_error": "",
            "last_full_sync_at": "",
            "pending_full_sync": False,
            "pending_scope_count": 0,
            "running": False,
        }


def test_runtime_schedules_due_retry_scope(tmp_path: Path) -> None:
    state = AppState(
        tmp_path / "config.json",
        tmp_path / "retry_state.json",
        tmp_path / "app.log",
    )
    state.update_config(
        {
            "local_path": str(tmp_path),
            "cloud_root_id": "1",
            "retry_interval_seconds": 30,
        }
    )
    state.record_instant_failure("目录A/文件.txt", "miss")
    retry_state = state._retry_state["目录A/文件.txt"]
    retry_state["last_instant_fail_at"] = (datetime.now(tz=UTC) - timedelta(seconds=31)).isoformat()
    state._write_json(state.retry_state_path, state._retry_state)

    app_paths = AppPaths(
        root=tmp_path,
        data_dir=tmp_path,
        config_path=tmp_path / "config.json",
        retry_state_path=tmp_path / "retry_state.json",
        log_path=tmp_path / "app.log",
        cookies_path=tmp_path / "115-cookies.txt",
    )
    sync_service = DummySyncService()
    runtime = RuntimeSupervisor(state, app_paths, sync_service)  # type: ignore[arg-type]

    runtime._schedule_retry_scopes(state.get_config())

    assert sync_service.scopes == ["目录A"]

from pathlib import Path

from sync115pan.store import AppState


def test_app_state_round_trip(tmp_path: Path) -> None:
    state = AppState(
        tmp_path / "config.json",
        tmp_path / "retry_state.json",
        tmp_path / "app.log",
    )

    config = state.update_config(
        {
            "auth_value": "UID=1; CID=2",
            "local_path": str(tmp_path),
            "cloud_root_id": "123",
            "cloud_path": "根目录 / 备份",
            "schedule_cron": "0 */6 * * *",
        }
    )
    assert config["cloud_root_id"] == "123"

    retry = state.record_instant_failure("demo.txt", "miss")
    assert retry["instant_fail_count"] == 1
    state.reset_retry_state("demo.txt")
    assert state.get_retry_state("demo.txt")["instant_fail_count"] == 0

    state.log("info", "测试日志")
    logs = state.list_logs()
    assert logs[0]["message"] == "测试日志"

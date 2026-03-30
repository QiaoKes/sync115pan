from pathlib import Path

from sync115pan.store import AppState, MAX_LOG_BYTES


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
    assert logs[0]["created_at"].endswith("+08:00")


def test_log_file_is_cleared_when_over_100mb(tmp_path: Path) -> None:
    log_path = tmp_path / "app.log"
    log_path.write_bytes(b"x" * (MAX_LOG_BYTES + 1))
    state = AppState(
        tmp_path / "config.json",
        tmp_path / "retry_state.json",
        log_path,
    )

    state.log("info", "新日志")

    content = log_path.read_text(encoding="utf-8")
    assert "新日志" in content
    assert "xxx" not in content
    assert len(content.encode("utf-8")) < 4096

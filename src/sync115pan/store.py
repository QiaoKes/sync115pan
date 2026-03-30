from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import threading
from typing import Any


SHANGHAI_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
MAX_LOG_BYTES = 100 * 1024 * 1024


def utcnow() -> datetime:
    return datetime.now(tz=SHANGHAI_TZ)


def isoformat(dt: datetime | None = None) -> str:
    return (dt or utcnow()).replace(microsecond=0).isoformat()


DEFAULT_CONFIG: dict[str, Any] = {
    "auth_value": "",
    "local_path": "",
    "cloud_root_id": "",
    "cloud_path": "",
    "watch_enabled": True,
    "schedule_cron": "",
    "watch_mode": "auto",
    "debounce_seconds": 5,
    "stability_check_seconds": 3,
    "max_instant_failures": 3,
    "retry_interval_seconds": 300,
}


class AppState:
    def __init__(self, config_path: Path, retry_state_path: Path, log_path: Path) -> None:
        self.config_path = config_path
        self.retry_state_path = retry_state_path
        self.log_path = log_path
        self._lock = threading.RLock()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config = self._load_json(self.config_path, DEFAULT_CONFIG)
        self._retry_state = self._load_json(self.retry_state_path, {})

    def close(self) -> None:
        return

    def _load_json(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return dict(default)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return dict(default)
        if not isinstance(data, dict):
            return dict(default)
        return {**default, **data}

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_config(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._config)

    def update_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        # 单配置模式下直接覆盖合并后的配置对象，不再维护多条同步路径和数据库迁移逻辑。
        normalized = {**self._config, **payload}
        normalized["watch_enabled"] = bool(normalized.get("watch_enabled", True))
        normalized["debounce_seconds"] = max(int(normalized.get("debounce_seconds", 5)), 1)
        normalized["stability_check_seconds"] = max(int(normalized.get("stability_check_seconds", 3)), 1)
        normalized["max_instant_failures"] = max(int(normalized.get("max_instant_failures", 3)), 1)
        normalized["retry_interval_seconds"] = max(int(normalized.get("retry_interval_seconds", 300)), 0)
        normalized["watch_mode"] = str(normalized.get("watch_mode", "auto") or "auto")
        normalized["schedule_cron"] = str(normalized.get("schedule_cron", "") or "").strip()
        normalized["auth_value"] = str(normalized.get("auth_value", "") or "")
        normalized["local_path"] = str(normalized.get("local_path", "") or "")
        normalized["cloud_root_id"] = str(normalized.get("cloud_root_id", "") or "")
        normalized["cloud_path"] = str(normalized.get("cloud_path", "") or "")
        with self._lock:
            self._config = normalized
            self._write_json(self.config_path, self._config)
            return dict(self._config)

    def get_retry_state(self, relative_path: str) -> dict[str, Any]:
        with self._lock:
            state = self._retry_state.get(relative_path)
            if isinstance(state, dict):
                return dict(state)
            return {
                "relative_path": relative_path,
                "instant_fail_count": 0,
                "last_instant_fail_at": None,
                "last_error": None,
            }

    def record_instant_failure(self, relative_path: str, error: str) -> dict[str, Any]:
        with self._lock:
            current = self.get_retry_state(relative_path)
            current["instant_fail_count"] = int(current["instant_fail_count"]) + 1
            current["last_instant_fail_at"] = isoformat()
            current["last_error"] = error
            self._retry_state[relative_path] = current
            self._write_json(self.retry_state_path, self._retry_state)
            return dict(current)

    def reset_retry_state(self, relative_path: str) -> None:
        with self._lock:
            if relative_path in self._retry_state:
                self._retry_state.pop(relative_path, None)
                self._write_json(self.retry_state_path, self._retry_state)

    def list_retry_states(self) -> list[dict[str, Any]]:
        with self._lock:
            rows: list[dict[str, Any]] = []
            for relative_path, payload in self._retry_state.items():
                if not isinstance(payload, dict):
                    continue
                rows.append(
                    {
                        "relative_path": relative_path,
                        "instant_fail_count": int(payload.get("instant_fail_count", 0) or 0),
                        "last_instant_fail_at": payload.get("last_instant_fail_at"),
                        "last_error": payload.get("last_error"),
                    }
                )
            return rows

    def log(self, level: str, message: str) -> None:
        record = {
            "level": level,
            "message": message,
            "created_at": isoformat(),
        }
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            if self.log_path.exists():
                try:
                    if self.log_path.stat().st_size > MAX_LOG_BYTES:
                        self.log_path.write_text("", encoding="utf-8")
                except OSError:
                    pass
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def list_logs(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        records: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                records.append(payload)
        records.reverse()
        return records

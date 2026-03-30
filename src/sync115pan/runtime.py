from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import threading
import time
from typing import Any

from croniter import croniter
from watchfiles import watch

from .config import AppPaths, is_docker
from .localfs import dedupe_scopes
from .store import AppState
from .syncer import SyncService, parse_iso8601, relative_parent


def resolve_watch_mode(mode: str) -> tuple[str, bool]:
    if mode == "polling":
        return "polling", True
    if mode == "native":
        return "native", False
    if is_docker():
        return "polling", True
    return "native", False


class RuntimeSupervisor:
    def __init__(self, state: AppState, app_paths: AppPaths, sync_service: SyncService) -> None:
        self.state = state
        self.app_paths = app_paths
        self.sync_service = sync_service
        self._watcher: tuple[threading.Thread, threading.Event] | None = None
        self._scheduler_stop = threading.Event()
        self._scheduler_thread: threading.Thread | None = None
        self._last_cron_tick = ""

    def start(self) -> None:
        self.sync_service.start()
        self.reload()
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return
        self._scheduler_stop.clear()
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, name="scheduler", daemon=True)
        self._scheduler_thread.start()

    def stop(self) -> None:
        self._stop_watcher()
        self._scheduler_stop.set()
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=5)
        self.sync_service.stop()

    def reload(self) -> None:
        self._stop_watcher()
        config = self.state.get_config()
        if not config["watch_enabled"] or not config["local_path"]:
            return
        local_root = Path(config["local_path"]).expanduser()
        if not local_root.exists():
            return
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._watch_loop,
            args=(local_root.resolve(), config, stop_event),
            name="watch-global",
            daemon=True,
        )
        self._watcher = (thread, stop_event)
        thread.start()
        self.state.log("info", "本地监听已启动")

    def runtime_info(self) -> dict[str, Any]:
        config = self.state.get_config()
        watch_mode = resolve_watch_mode(str(config["watch_mode"]))[0] if config["local_path"] else "auto"
        return {
            "docker": is_docker(),
            "watch_mode": watch_mode,
            "watcher_running": self._watcher is not None,
            "sync": self.sync_service.snapshot(),
        }

    def _stop_watcher(self) -> None:
        watcher = self._watcher
        if watcher is None:
            return
        thread, stop_event = watcher
        stop_event.set()
        thread.join(timeout=5)
        self._watcher = None
        self.state.log("info", "本地监听已停止")

    def _watch_loop(self, local_root: Path, config: dict[str, Any], stop_event: threading.Event) -> None:
        watch_mode, force_polling = resolve_watch_mode(str(config["watch_mode"]))
        debounce_ms = max(int(config["debounce_seconds"]), 1) * 1000
        for changes in watch(
            local_root,
            recursive=True,
            stop_event=stop_event,
            debounce=debounce_ms,
            force_polling=force_polling,
        ):
            changed_paths = [change[1] for change in changes]
            scopes = dedupe_scopes(local_root, changed_paths) or [""]
            for scope in scopes:
                self.sync_service.request_recheck(scope)
            if len(changed_paths) == 1 and len(scopes) == 1:
                self.state.log("info", f"检测到本地变更：{changed_paths[0]}，已安排增量检查 {scopes[0] or '/'}")
            else:
                preview = "；".join(changed_paths[:3])
                suffix = " ..." if len(changed_paths) > 3 else ""
                self.state.log(
                    "info",
                    f"检测到本地变更：{len(changed_paths)} 个路径，示例：{preview}{suffix}，已安排增量检查 {len(scopes)} 个目录",
                )

    def _scheduler_loop(self) -> None:
        while not self._scheduler_stop.is_set():
            config = self.state.get_config()
            cron_expr = str(config["schedule_cron"] or "").strip()
            now = datetime.now().replace(second=0, microsecond=0)
            tick = now.isoformat()
            if cron_expr and tick != self._last_cron_tick:
                try:
                    if croniter.match(cron_expr, now):
                        self.sync_service.request_full_sync("cron")
                        self._last_cron_tick = tick
                except Exception as exc:
                    self.state.log("error", f"Cron 表达式无效：{exc}")
                    self._last_cron_tick = tick
            self._schedule_retry_scopes(config)
            time.sleep(15)

    def _schedule_retry_scopes(self, config: dict[str, Any]) -> None:
        if not config.get("local_path") or not config.get("cloud_root_id"):
            return
        due_scopes: set[str] = set()
        interval_seconds = int(config.get("retry_interval_seconds", 300))
        for item in self.state.list_retry_states():
            last_fail = parse_iso8601(item.get("last_instant_fail_at"))
            if last_fail is None:
                continue
            if (datetime.now(tz=UTC) - last_fail).total_seconds() < interval_seconds:
                continue
            due_scopes.add(relative_parent(str(item["relative_path"])))
        for scope in sorted(due_scopes):
            self.sync_service.request_recheck(scope)
        if due_scopes:
            self.state.log("info", f"已安排秒传重试：涉及 {len(due_scopes)} 个目录")

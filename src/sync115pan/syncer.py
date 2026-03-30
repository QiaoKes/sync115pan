from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
import threading
from typing import Any

from .cloud115 import Cloud115Error, Cloud115Service
from .config import AppPaths
from .localfs import wait_for_file_stable, walk_local_tree
from .store import AppState, isoformat


def parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def relative_parent(path: str) -> str:
    parent = PurePosixPath(path).parent.as_posix() if path else ""
    return "" if parent == "." else parent


class SyncService:
    def __init__(self, state: AppState, app_paths: AppPaths) -> None:
        self.state = state
        self.app_paths = app_paths
        self._condition = threading.Condition()
        self._stop = False
        self._thread: threading.Thread | None = None
        self._pending_full_sync = False
        self._pending_scopes: set[str] = set()
        self._status = "idle"
        self._current_job = ""
        self._last_error = ""
        self._last_full_sync_at = ""

    def _write_debug_snapshot(self, name: str, lines: list[str]) -> Path:
        debug_dir = self.app_paths.data_dir / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = debug_dir / f"{stamp}-{name}.txt"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run_loop, name="sync-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._condition:
            self._stop = True
            self._condition.notify_all()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def request_full_sync(self, source: str = "manual") -> None:
        with self._condition:
            current_status = self._status
            pending_full_sync = self._pending_full_sync
            self._pending_full_sync = True
            self._pending_scopes.clear()
            self._condition.notify_all()
        self.state.log(
            "info",
            f"已请求全量同步：来源={source}，当前状态={current_status}，原待执行全量={pending_full_sync}",
        )

    def request_recheck(self, scope: str) -> None:
        with self._condition:
            if self._pending_full_sync:
                return
            self._pending_scopes.add(scope)
            self._condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return {
                "status": self._status,
                "current_job": self._current_job,
                "last_error": self._last_error,
                "last_full_sync_at": self._last_full_sync_at,
                "pending_full_sync": self._pending_full_sync,
                "pending_scope_count": len(self._pending_scopes),
                "running": self._status == "running",
            }

    def _run_loop(self) -> None:
        while True:
            with self._condition:
                while not self._stop and not self._pending_full_sync and not self._pending_scopes:
                    self._condition.wait(timeout=1)
                if self._stop:
                    return
                if self._pending_full_sync:
                    job_kind = "full_scan"
                    scopes: list[str] = []
                    self._pending_full_sync = False
                    self._pending_scopes.clear()
                else:
                    job_kind = "incremental_recheck"
                    scopes = sorted(self._pending_scopes)
                    self._pending_scopes.clear()
                self._status = "running"
                self._current_job = job_kind
                self._last_error = ""
            try:
                if job_kind == "full_scan":
                    self._run_full_sync()
                else:
                    self._run_incremental(scopes)
            except Exception as exc:
                with self._condition:
                    self._status = "error"
                    self._current_job = ""
                    self._last_error = str(exc)
                self.state.log("error", f"同步失败：{exc}")
            else:
                with self._condition:
                    self._status = "idle"
                    self._current_job = ""

    def _current_config(self) -> dict[str, Any]:
        config = self.state.get_config()
        if not config["auth_value"]:
            raise Cloud115Error("115 Cookie 尚未配置")
        if not config["local_path"]:
            raise RuntimeError("本地目录尚未配置")
        if not config["cloud_root_id"]:
            raise RuntimeError("云盘目录尚未配置")
        return config

    def _make_cloud(self, config: dict[str, Any]) -> Cloud115Service:
        return Cloud115Service(
            auth_value=config["auth_value"],
            cookies_path=self.app_paths.cookies_path,
        )

    def _run_full_sync(self) -> None:
        config = self._current_config()
        local_root = Path(config["local_path"]).expanduser().resolve()
        cloud = self._make_cloud(config)
        local_rows = walk_local_tree(local_root)
        local_map = {row["relative_path"]: row for row in local_rows}
        raw_cloud_paths, cloud_entries = cloud.export_tree_debug(config["cloud_root_id"])
        cloud_paths = {entry.relative_path for entry in cloud_entries}
        missing_dirs = sorted(
            [path for path, row in local_map.items() if row["is_dir"] and path not in cloud_paths],
            key=lambda item: item.count("/"),
        )
        missing_files = sorted(
            [path for path, row in local_map.items() if not row["is_dir"] and path not in cloud_paths]
        )
        dir_cache = {"": int(config["cloud_root_id"])}
        self.state.log(
            "info",
            f"全量检查：本地 {len(local_rows)} 条，云端 {len(cloud_paths)} 条，待创建目录 {len(missing_dirs)} 个，待同步文件 {len(missing_files)} 个",
        )
        # 调试快照先保留实现但默认停用，避免全量同步时持续导出本地树和云端树文件。
        # local_snapshot = self._write_debug_snapshot(
        #     "full-local-tree",
        #     [f"{'DIR' if row['is_dir'] else 'FILE'}\t{row['relative_path']}" for row in local_rows],
        # )
        # raw_cloud_snapshot = self._write_debug_snapshot("full-cloud-export-raw", raw_cloud_paths)
        # normalized_cloud_snapshot = self._write_debug_snapshot(
        #     "full-cloud-export-normalized",
        #     [entry.relative_path for entry in cloud_entries],
        # )
        # missing_snapshot = self._write_debug_snapshot(
        #     "full-missing-paths",
        #     ["[DIR] " + path for path in missing_dirs] + ["[FILE] " + path for path in missing_files],
        # )
        # self.state.log(
        #     "info",
        #     f"全量排障快照已写入：本地树={local_snapshot.name}，云端原始树={raw_cloud_snapshot.name}，云端归一化树={normalized_cloud_snapshot.name}，缺失清单={missing_snapshot.name}",
        # )
        self._ensure_directories(cloud, missing_dirs, dir_cache)
        self._upload_missing_files(config, cloud, local_root, missing_files, dir_cache)
        with self._condition:
            self._last_full_sync_at = isoformat()
        self.state.log("info", f"全量同步完成：创建目录 {len(missing_dirs)} 个，同步文件 {len(missing_files)} 个")

    def _run_incremental(self, scopes: list[str]) -> None:
        if not scopes:
            return
        config = self._current_config()
        local_root = Path(config["local_path"]).expanduser().resolve()
        cloud = self._make_cloud(config)
        dir_cache = {"": int(config["cloud_root_id"])}
        total_missing_dirs: list[str] = []
        total_missing_files: list[str] = []
        for scope in scopes:
            missing_dirs, missing_files = self._sync_scope(config, cloud, local_root, scope, dir_cache)
            total_missing_dirs.extend(missing_dirs)
            total_missing_files.extend(missing_files)
        if total_missing_dirs or len(total_missing_files) > 1:
            scope_text = "、".join(scope or "/" for scope in scopes)
            dir_text = "；".join(total_missing_dirs[:5]) if total_missing_dirs else "无"
            file_text = "；".join(str(local_root / Path(path)) for path in total_missing_files[:5]) if total_missing_files else "无"
            suffix = " ..." if len(total_missing_dirs) > 5 or len(total_missing_files) > 5 else ""
            self.state.log(
                "info",
                f"增量检查完成：范围={scope_text}，待创建目录={dir_text}，待同步文件={file_text}{suffix}",
            )

    def _sync_scope(
        self,
        config: dict[str, Any],
        cloud: Cloud115Service,
        local_root: Path,
        scope: str,
        dir_cache: dict[str, int],
    ) -> tuple[list[str], list[str]]:
        local_rows = walk_local_tree(local_root, scope=scope)
        local_map = {row["relative_path"]: row for row in local_rows}
        cloud_paths: set[str] = set()
        if scope:
            try:
                remote_scope_id = self._resolve_remote_directory_id(cloud, scope, dir_cache)
            except Cloud115Error:
                remote_scope_id = None
            if remote_scope_id is not None:
                cloud_paths = {entry.relative_path for entry in cloud.walk_tree(remote_scope_id, scope)}
        else:
            cloud_paths = {entry.relative_path for entry in cloud.walk_tree(int(config["cloud_root_id"]))}
        missing_dirs = sorted(
            [path for path, row in local_map.items() if row["is_dir"] and path not in cloud_paths],
            key=lambda item: item.count("/"),
        )
        missing_files = sorted(
            [path for path, row in local_map.items() if not row["is_dir"] and path not in cloud_paths]
        )
        self._ensure_directories(cloud, missing_dirs, dir_cache)
        self._upload_missing_files(config, cloud, local_root, missing_files, dir_cache)
        return missing_dirs, missing_files

    def _resolve_remote_directory_id(
        self,
        cloud: Cloud115Service,
        relative_path: str,
        dir_cache: dict[str, int],
    ) -> int | None:
        if not relative_path:
            return dir_cache[""]
        if relative_path in dir_cache:
            return dir_cache[relative_path]

        current_remote_id = dir_cache[""]
        current_path = ""
        for part in PurePosixPath(relative_path).parts:
            current_path = "/".join(filter(None, (current_path, part)))
            if current_path in dir_cache:
                current_remote_id = dir_cache[current_path]
                continue
            children = cloud.list_directory(current_remote_id)
            matched = next((entry for entry in children if entry.is_dir and entry.name == part), None)
            if matched is None:
                return None
            current_remote_id = matched.remote_id
            dir_cache[current_path] = current_remote_id
        return current_remote_id

    def _ensure_directories(
        self,
        cloud: Cloud115Service,
        missing_dirs: list[str],
        dir_cache: dict[str, int],
    ) -> None:
        for relative_path in missing_dirs:
            name = PurePosixPath(relative_path).name
            parent_path = relative_parent(relative_path)
            parent_remote_id = self._resolve_remote_directory_id(cloud, parent_path, dir_cache)
            if parent_remote_id is None:
                raise Cloud115Error(f"云端父目录不存在：{parent_path or '/'}")
            remote_id = cloud.ensure_directory(parent_remote_id, name)
            dir_cache[relative_path] = remote_id
            self.state.log("info", f"已创建云端目录：/{relative_path}")

    def _upload_missing_files(
        self,
        config: dict[str, Any],
        cloud: Cloud115Service,
        local_root: Path,
        missing_files: list[str],
        dir_cache: dict[str, int],
    ) -> None:
        for relative_path in missing_files:
            local_path = local_root / Path(relative_path)
            cloud_path = f"/{relative_path}" if relative_path else "/"
            if not local_path.exists():
                self.state.reset_retry_state(relative_path)
                continue
            if not wait_for_file_stable(local_path, int(config["stability_check_seconds"])):
                self.state.log("warning", f"文件仍在写入，稍后重试：本地={local_path}，云端={cloud_path}")
                self.request_recheck(relative_parent(relative_path))
                continue

            parent_path = relative_parent(relative_path)
            parent_remote_id = self._resolve_remote_directory_id(cloud, parent_path, dir_cache)
            if parent_remote_id is None:
                raise Cloud115Error(f"云端目录不存在或无法定位：{parent_path or '/'}")

            instant = cloud.attempt_instant_upload(local_path, parent_remote_id, local_path.name)
            response = instant["response"]
            if response.get("reuse"):
                self.state.reset_retry_state(relative_path)
                self.state.log("info", f"文件已同步：方式=秒传，本地={local_path}，云端={cloud_path}")
                continue

            error_text = str(response.get("statusmsg") or response.get("message") or "instant upload miss")
            existing_retry = self.state.get_retry_state(relative_path)
            fail_count = int(existing_retry["instant_fail_count"]) + 1
            last_fail = parse_iso8601(existing_retry.get("last_instant_fail_at"))
            interval_seconds = int(config["retry_interval_seconds"])
            can_fallback = fail_count >= int(config["max_instant_failures"]) and (
                last_fail is None or (datetime.now(tz=UTC) - last_fail).total_seconds() >= interval_seconds
            )
            current_retry = self.state.record_instant_failure(relative_path, error_text)
            if not can_fallback:
                self.state.log(
                    "info",
                    f"文件待重试：本地={local_path}，云端={cloud_path}，方式=秒传，第 {current_retry['instant_fail_count']} 次",
                )
                continue

            cloud.upload_multipart(
                local_path,
                parent_remote_id,
                local_path.name,
                instant["filesha1"],
                int(instant["filesize"]),
            )
            self.state.reset_retry_state(relative_path)
            self.state.log("info", f"文件已同步：方式=普通上传，本地={local_path}，云端={cloud_path}")

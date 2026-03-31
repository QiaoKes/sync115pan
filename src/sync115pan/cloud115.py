from __future__ import annotations

from functools import cached_property
from pathlib import Path, PurePosixPath
import hashlib
import os
import threading
import time
from typing import Any

from p115client import P115Client
from p115client.tool.export_dir import export_dir_parse_iter
from p115client.tool.upload import P115MultipartUpload, upload_init


class Cloud115Error(RuntimeError):
    pass


class Cloud115Service:
    _rate_limit_lock = threading.Lock()
    _next_allowed_at = 0.0

    def __init__(self, auth_value: str, cookies_path: Path, cooldown: float = 1.0) -> None:
        self.auth_value = auth_value
        self.cookies_path = cookies_path
        self.cooldown = cooldown

    def _rate_limit(self) -> None:
        # 进程内统一节流 115 请求，避免目录读取、mkdir 和上传初始化过快触发风控。
        with self._rate_limit_lock:
            now = time.monotonic()
            wait_seconds = self._next_allowed_at - now
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self._next_allowed_at = time.monotonic() + self.cooldown

    def configured(self) -> bool:
        return bool(self.auth_value)

    def _cookie_source(self) -> Path:
        if "=" not in self.auth_value:
            raise Cloud115Error("Cookie 格式无效，请粘贴完整的 name=value; name2=value2 内容")
        self.cookies_path.write_text(self.auth_value.strip(), encoding="utf-8")
        return self.cookies_path

    @cached_property
    def client(self) -> P115Client:
        if not self.configured():
            raise Cloud115Error("115 Cookie 尚未配置。")
        try:
            return P115Client(self._cookie_source(), check_for_relogin=True)
        except Exception as exc:  # pragma: no cover
            raise Cloud115Error(f"115 Cookie 初始化失败：{exc}") from exc

    def _normalize_cloud_root_path(self, cloud_root_path: str) -> str:
        cleaned = str(cloud_root_path or "").strip()
        if not cleaned or cleaned == "/":
            return "/"
        normalized = cleaned.replace(" / ", "/").strip("/")
        return f"/{normalized}"

    def _resolve_export_root_prefix(self, raw_paths: list[str], cloud_root_path: str) -> str:
        normalized_root = self._normalize_cloud_root_path(cloud_root_path)
        if normalized_root == "/":
            return "/"

        raw_set = {path for path in raw_paths if path}
        root_parts = [part for part in PurePosixPath(normalized_root).parts if part != "/"]
        for index in range(len(root_parts)):
            candidate = "/" + "/".join(root_parts[index:])
            if candidate in raw_set:
                return candidate
            if any(path.startswith(candidate + "/") for path in raw_set):
                return candidate
        raise Cloud115Error(f"导出目录树与所选云盘目录不匹配：所选={normalized_root}，导出首层={raw_paths[:5]!r}")

    def _normalize_export_paths(self, raw_paths: list[str], cloud_root_path: str) -> set[str]:
        if not raw_paths:
            return set()

        root_prefix = self._resolve_export_root_prefix(raw_paths, cloud_root_path)

        relative_paths: set[str] = set()
        for raw_path in raw_paths:
            if not raw_path or raw_path == "/":
                continue
            if root_prefix == "/":
                relative_path = raw_path.removeprefix("/")
            else:
                if raw_path == root_prefix:
                    continue
                if not raw_path.startswith(root_prefix + "/"):
                    continue
                relative_path = raw_path.removeprefix(root_prefix).removeprefix("/")
            if relative_path:
                relative_paths.add(relative_path)
        return relative_paths

    def export_relative_paths(
        self,
        root_id: int | str,
        cloud_root_path: str,
        *,
        include_raw: bool = False,
    ) -> set[str] | tuple[list[str], set[str]]:
        try:
            self._rate_limit()
            raw_paths = [str(item) for item in export_dir_parse_iter(self.client, export_file_ids=root_id, timeout=0)]
        except Exception as exc:  # pragma: no cover
            raise Cloud115Error(f"导出云端目录树失败：{exc}") from exc
        relative_paths = self._normalize_export_paths(raw_paths, cloud_root_path)
        if include_raw:
            return raw_paths, relative_paths
        return relative_paths

    def list_children(self, parent_id: int | str) -> tuple[dict[str, int], set[str]]:
        directories: dict[str, int] = {}
        files: set[str] = set()
        offset = 0
        limit = 1150
        try:
            while True:
                self._rate_limit()
                resp = self.client.fs_files_app(
                    {
                        "cid": int(parent_id),
                        "limit": limit,
                        "offset": offset,
                        "show_dir": 1,
                        "count_folders": 1,
                        "cur": 1,
                    },
                    app="android",
                )
                data = list(resp.get("data") or [])
                if not data:
                    break
                for item in data:
                    name = str(item["fn"])
                    entry_id = int(item["fid"])
                    is_dir = str(item.get("fc", "")) == "0"
                    if is_dir:
                        directories[name] = entry_id
                    else:
                        files.add(name)
                if len(data) < limit:
                    break
                offset += len(data)
        except Exception as exc:  # pragma: no cover
            raise Cloud115Error(f"读取云盘目录失败：{exc}") from exc
        return directories, files

    def resolve_remote_dir(
        self,
        root_id: int | str,
        relative_dir: str,
        dir_cache: dict[str, int] | None = None,
    ) -> int | None:
        root_id = int(root_id)
        cache = dir_cache if dir_cache is not None else {}
        cache.setdefault("", root_id)
        if not relative_dir:
            return root_id
        if relative_dir in cache:
            return cache[relative_dir]

        current_id = root_id
        current_path = ""
        for part in PurePosixPath(relative_dir).parts:
            current_path = "/".join(filter(None, (current_path, part)))
            if current_path in cache:
                current_id = cache[current_path]
                continue
            directories, _ = self.list_children(current_id)
            next_id = directories.get(part)
            if next_id is None:
                return None
            cache[current_path] = next_id
            current_id = next_id
        return current_id

    def ensure_remote_dir(
        self,
        root_id: int | str,
        relative_dir: str,
        dir_cache: dict[str, int] | None = None,
    ) -> tuple[int, bool]:
        root_id = int(root_id)
        cache = dir_cache if dir_cache is not None else {}
        cache.setdefault("", root_id)
        if not relative_dir:
            return root_id, False

        remote_id = self.resolve_remote_dir(root_id, relative_dir, cache)
        if remote_id is not None:
            return remote_id, False

        relative_path = PurePosixPath(relative_dir)
        parent_dir = relative_path.parent.as_posix()
        if parent_dir == ".":
            parent_dir = ""
        parent_id, _ = self.ensure_remote_dir(root_id, parent_dir, cache)
        name = relative_path.name

        self._rate_limit()
        response = self.client.fs_mkdir(name, parent_id)
        if "cid" in response:
            remote_id = int(response["cid"])
            cache[relative_dir] = remote_id
            return remote_id, True

        directories, _ = self.list_children(parent_id)
        if name in directories:
            remote_id = directories[name]
            cache[relative_dir] = remote_id
            return remote_id, False
        raise Cloud115Error(f"创建或定位云端目录失败：{relative_dir!r} -> {response!r}")

    def attempt_instant_upload(self, local_path: Path, parent_id: int, filename: str) -> dict[str, Any]:
        size = local_path.stat().st_size
        filesha1 = sha1_for_file(local_path)
        try:
            self._rate_limit()
            response = upload_init(
                self.client,
                os.fspath(local_path),
                pid=parent_id,
                filename=filename,
                filesha1=filesha1,
                filesize=size,
            )
        except Exception as exc:  # pragma: no cover
            raise Cloud115Error(f"初始化上传失败：{exc}") from exc
        return {"filesize": size, "filesha1": filesha1, "response": response}

    def upload_multipart(self, local_path: Path, parent_id: int, filename: str, filesha1: str, filesize: int) -> dict[str, Any]:
        try:
            self._rate_limit()
            uploader = P115MultipartUpload.from_path(
                os.fspath(local_path),
                pid=parent_id,
                filename=filename,
                filesha1=filesha1,
                filesize=filesize,
                user_id=self.client.user_id,
                user_key=self.client.user_key,
            )
        except Exception as exc:  # pragma: no cover
            raise Cloud115Error(f"创建普通上传任务失败：{exc}") from exc
        if isinstance(uploader, dict):
            return uploader
        for _ in uploader.iter_upload():
            pass
        return uploader.complete()


def sha1_for_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while chunk := handle.read(block_size):
            digest.update(chunk)
    return digest.hexdigest().upper()

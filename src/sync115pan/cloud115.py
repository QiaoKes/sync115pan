from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
import hashlib
import importlib
import os
from typing import Any


class Cloud115Error(RuntimeError):
    pass


@dataclass(slots=True)
class RemoteEntry:
    relative_path: str
    remote_id: int
    parent_remote_id: int
    name: str
    is_dir: bool


class Cloud115Service:
    def __init__(self, auth_value: str, cookies_path: Path, cooldown: float = 0.3) -> None:
        self.auth_value = auth_value
        self.cookies_path = cookies_path
        self.cooldown = cooldown

    @cached_property
    def _api(self) -> dict[str, Any]:
        try:
            client_module = importlib.import_module("p115client")
            export_module = importlib.import_module("p115client.tool.export_dir")
            fs_module = importlib.import_module("p115client.tool.fs_files")
            attr_module = importlib.import_module("p115client.tool.attr")
            upload_module = importlib.import_module("p115client.tool.upload")
        except Exception as exc:  # pragma: no cover
            raise Cloud115Error(
                "p115client is not available. Install project dependencies with Python 3.12+."
            ) from exc
        return {
            "P115Client": client_module.P115Client,
            "export_dir_parse_iter": export_module.export_dir_parse_iter,
            "iter_fs_files_serialized": fs_module.iter_fs_files_serialized,
            "normalize_attr": attr_module.normalize_attr,
            "upload_init": upload_module.upload_init,
            "P115MultipartUpload": upload_module.P115MultipartUpload,
        }

    def configured(self) -> bool:
        return bool(self.auth_value)

    def _cookie_source(self) -> str | Path:
        # 统一把用户粘贴的 Cookie 落到本地文件，再交给 p115client 读取，避免字符串和路径模式混用。
        if "=" not in self.auth_value:
            raise Cloud115Error("Cookie 格式无效，请粘贴完整的 name=value; name2=value2 内容")
        self.cookies_path.write_text(self.auth_value.strip(), encoding="utf-8")
        return self.cookies_path

    @cached_property
    def client(self) -> Any:
        if not self.configured():
            raise Cloud115Error("115 Cookie 尚未配置。")
        try:
            return self._api["P115Client"](self._cookie_source(), check_for_relogin=True)
        except Exception as exc:  # pragma: no cover
            raise Cloud115Error(f"115 Cookie 初始化失败：{exc}") from exc

    def list_directory(self, parent_id: int | str) -> list[RemoteEntry]:
        entries: list[RemoteEntry] = []
        try:
            # 目录选择器和同步索引都依赖这个入口，因此这里直接归一化成内部统一的 RemoteEntry 结构。
            iterator = self._api["iter_fs_files_serialized"](
                self.client,
                parent_id,
                app="web",
                cooldown=self.cooldown,
            )
            for page in iterator:
                for item in page["data"]:
                    attr = self._api["normalize_attr"](item, simple=True)
                    entries.append(
                        RemoteEntry(
                            relative_path="",
                            remote_id=int(attr["id"]),
                            parent_remote_id=int(attr["parent_id"]),
                            name=str(attr["name"]),
                            is_dir=bool(attr["is_dir"]),
                        )
                    )
        except Cloud115Error:
            raise
        except Exception as exc:  # pragma: no cover
            raise Cloud115Error(f"读取云盘目录失败：{exc}") from exc
        return entries

    def walk_tree(self, root_id: int | str, base_relative_path: str = "") -> list[RemoteEntry]:
        # 增量同步只对局部目录做递归展开，这里沿用目录级遍历，不在热路径里调用高风险的路径补全接口。
        results: list[RemoteEntry] = []
        queue: list[tuple[int, str]] = [(root_id, base_relative_path)]
        while queue:
            parent_id, relative_prefix = queue.pop(0)
            for entry in self.list_directory(parent_id):
                relative_path = "/".join(p for p in (relative_prefix, entry.name) if p)
                normalized = RemoteEntry(
                    relative_path=relative_path,
                    remote_id=entry.remote_id,
                    parent_remote_id=entry.parent_remote_id,
                    name=entry.name,
                    is_dir=entry.is_dir,
                )
                results.append(normalized)
                if entry.is_dir:
                    queue.append((entry.remote_id, relative_path))
        return results

    def _export_paths(self, root_id: int | str) -> list[str]:
        try:
            paths = [
                str(item)
                for item in self._api["export_dir_parse_iter"](self.client, export_file_ids=root_id, timeout=0)
            ]
        except Exception as exc:  # pragma: no cover
            raise Cloud115Error(f"导出云端目录树失败：{exc}") from exc
        return paths

    def export_tree_debug(self, root_id: int | str) -> tuple[list[str], list[RemoteEntry]]:
        # 排障时同时保留导出接口的原始路径和归一化后的相对路径，便于定位路径裁剪或快照延迟问题。
        paths = self._export_paths(root_id)
        if not paths:
            return [], []

        root_marker = str(paths[0])
        sync_root_marker = root_marker
        if root_marker == "/" and len(paths) > 1:
            sync_root_marker = str(paths[1])
        entries: list[RemoteEntry] = []
        for raw_path in paths:
            if raw_path == root_marker:
                continue
            if raw_path == sync_root_marker:
                continue
            if sync_root_marker == "/":
                relative_path = raw_path.removeprefix("/")
            else:
                relative_path = raw_path.removeprefix(sync_root_marker).removeprefix("/")
            if not relative_path:
                continue
            name = relative_path.rsplit("/", 1)[-1]
            entries.append(
                RemoteEntry(
                    relative_path=relative_path,
                    remote_id=0,
                    parent_remote_id=0,
                    name=name,
                    is_dir=True,
                )
            )
        return paths, entries

    def export_tree(self, root_id: int | str) -> list[RemoteEntry]:
        # 导出接口一次性返回整棵目录树的路径清单，适合全量对比；这里不追求节点详细属性，只保留路径存在性。
        _, entries = self.export_tree_debug(root_id)
        return entries

    def ensure_directory(self, parent_id: int, name: str) -> int:
        response = self.client.fs_mkdir(name, parent_id)
        if "cid" in response:
            return int(response["cid"])
        for entry in self.list_directory(parent_id):
            if entry.is_dir and entry.name == name:
                return entry.remote_id
        raise Cloud115Error(f"Failed to create or resolve remote directory {name!r}: {response!r}")

    def attempt_instant_upload(self, local_path: Path, parent_id: int, filename: str) -> dict[str, Any]:
        size = local_path.stat().st_size
        filesha1 = sha1_for_file(local_path)
        response = self._api["upload_init"](
            self.client,
            os.fspath(local_path),
            pid=parent_id,
            filename=filename,
            filesha1=filesha1,
            filesize=size,
        )
        return {"filesize": size, "filesha1": filesha1, "response": response}

    def upload_multipart(self, local_path: Path, parent_id: int, filename: str, filesha1: str, filesize: int) -> dict[str, Any]:
        uploader = self._api["P115MultipartUpload"].from_path(
            os.fspath(local_path),
            pid=parent_id,
            filename=filename,
            filesha1=filesha1,
            filesize=filesize,
            user_id=self.client.user_id,
            user_key=self.client.user_key,
        )
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

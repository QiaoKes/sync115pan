from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Iterable
import os


def to_posix_relative(path: Path, root: Path) -> str:
    relative = path.resolve().relative_to(root.resolve())
    if not relative.parts:
        return ""
    return PurePosixPath(*relative.parts).as_posix()


def to_local_path(relative_path: str, root: Path) -> Path:
    if not relative_path:
        return root.resolve()
    return root.resolve().joinpath(*PurePosixPath(relative_path).parts)


def walk_local_tree(root: Path, scope: str = "") -> list[dict]:
    scope_path = to_local_path(scope, root) if scope else root
    if not scope_path.exists():
        return []

    records: list[dict] = []
    root_resolved = root.resolve()
    stack = [scope_path]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            scanned = sorted(entries, key=lambda entry: entry.name.lower())
        for entry in scanned:
            entry_path = Path(entry.path)
            relative_path = to_posix_relative(entry_path, root_resolved)
            stat = entry.stat(follow_symlinks=False)
            is_dir = entry.is_dir(follow_symlinks=False)
            records.append(
                {
                    "relative_path": relative_path,
                    "is_dir": is_dir,
                    "size": 0 if is_dir else stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
            if is_dir:
                stack.append(entry_path)
    return records


def dedupe_scopes(root: Path, changed_paths: Iterable[str]) -> list[str]:
    scopes: set[str] = set()
    for raw_path in changed_paths:
        path = Path(raw_path)
        try:
            relative = to_posix_relative(path, root)
        except (ValueError, OSError):
            continue
        parent = PurePosixPath(relative).parent.as_posix() if relative else ""
        if parent == ".":
            parent = ""
        scopes.add(parent)
    return sorted(scopes)


def wait_for_file_stable(path: Path, check_seconds: int) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        stat1 = path.stat()
    except OSError:
        return False
    import time

    time.sleep(max(check_seconds, 1))
    try:
        stat2 = path.stat()
    except OSError:
        return False
    return stat1.st_size == stat2.st_size and stat1.st_mtime_ns == stat2.st_mtime_ns

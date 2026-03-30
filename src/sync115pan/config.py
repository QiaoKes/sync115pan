from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(slots=True)
class AppPaths:
    root: Path
    data_dir: Path
    config_path: Path
    retry_state_path: Path
    log_path: Path
    cookies_path: Path

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


def is_docker() -> bool:
    if Path("/.dockerenv").exists():
        return True
    cgroup = Path("/proc/1/cgroup")
    if cgroup.exists():
        try:
            text = cgroup.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False
        return "docker" in text or "containerd" in text
    return os.getenv("container", "").lower() == "docker"


def default_app_paths() -> AppPaths:
    root = Path(__file__).resolve().parents[2]
    data_dir = Path(os.getenv("SYNC115PAN_DATA_DIR", root / ".data")).resolve()
    return AppPaths(
        root=root,
        data_dir=data_dir,
        config_path=data_dir / "config.json",
        retry_state_path=data_dir / "retry_state.json",
        log_path=data_dir / "app.log",
        cookies_path=data_dir / "115-cookies.txt",
    )

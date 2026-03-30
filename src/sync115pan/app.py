from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .cloud115 import Cloud115Service
from .config import default_app_paths, is_docker
from .runtime import RuntimeSupervisor
from .store import AppState
from .syncer import SyncService


def normalize_auth_value(auth_value: str) -> str:
    cleaned = auth_value.strip()
    parts = [part.strip().rstrip(";") for part in cleaned.replace("\r", "\n").split("\n") if part.strip()]
    return "; ".join(parts)


def normalize_cloud_path_display(cloud_path: str) -> str:
    cleaned = str(cloud_path or "").strip()
    if cleaned == "根目录":
        return "/"
    if cleaned.startswith("根目录 / "):
        return cleaned.removeprefix("根目录 / ")
    return cleaned


class ConfigPayload(BaseModel):
    auth_value: str = ""
    local_path: str = ""
    cloud_root_id: str = ""
    cloud_path: str = ""
    watch_enabled: bool = True
    schedule_cron: str = ""
    watch_mode: str = "auto"
    debounce_seconds: int = 5
    stability_check_seconds: int = 3
    max_instant_failures: int = 3
    retry_interval_seconds: int = 300


app_paths = default_app_paths()
state = AppState(app_paths.config_path, app_paths.retry_state_path, app_paths.log_path)
sync_service = SyncService(state, app_paths)
runtime = RuntimeSupervisor(state, app_paths, sync_service)
templates = Jinja2Templates(directory=os.fspath(Path(__file__).with_name("templates")))


@asynccontextmanager
async def lifespan(_: FastAPI):
    app_paths.ensure()
    runtime.start()
    try:
        yield
    finally:
        runtime.stop()
        state.close()


app = FastAPI(title="sync115pan", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.fspath(Path(__file__).with_name("static"))), name="static")

SYNC_STATUS_LABELS = {
    "idle": "空闲",
    "running": "同步中",
    "error": "异常",
}

WATCH_MODE_LABELS = {
    "auto": "自动",
    "native": "原生事件",
    "polling": "轮询",
}

JOB_LABELS = {
    "": "待命",
    "full_scan": "全量同步",
    "incremental_recheck": "增量重检",
}

def translated_runtime() -> dict[str, Any]:
    runtime_info = runtime.runtime_info()
    sync_info = dict(runtime_info["sync"])
    sync_info["status_label"] = SYNC_STATUS_LABELS.get(sync_info["status"], sync_info["status"])
    sync_info["current_job_label"] = JOB_LABELS.get(sync_info["current_job"], "待命")
    runtime_info["sync"] = sync_info
    configured_mode = str(state.get_config().get("watch_mode", "auto") or "auto")
    resolved_mode = str(runtime_info.get("watch_mode", configured_mode) or configured_mode)
    if configured_mode == "auto" and resolved_mode != "auto":
        runtime_info["watch_mode_label"] = f"自动（当前{WATCH_MODE_LABELS.get(resolved_mode, resolved_mode)}）"
    else:
        runtime_info["watch_mode_label"] = WATCH_MODE_LABELS.get(configured_mode, configured_mode)
    return runtime_info


def dashboard_context(request: Request) -> dict[str, Any]:
    config = state.get_config()
    config["cloud_path"] = normalize_cloud_path_display(config["cloud_path"])
    runtime_info = translated_runtime()
    return {
        "request": request,
        "config": config,
        "runtime": runtime_info,
        "logs": state.list_logs(limit=50),
        "auth_configured": bool(config["auth_value"]),
        "config_ready": bool(config["local_path"] and config["cloud_root_id"]),
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard.html", dashboard_context(request))


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    config = state.get_config()
    config["cloud_path"] = normalize_cloud_path_display(config["cloud_path"])
    return {
        **config,
        "auth_configured": bool(config["auth_value"]),
        "config_ready": bool(config["local_path"] and config["cloud_root_id"]),
    }


@app.put("/api/config")
async def put_config(payload: ConfigPayload) -> dict[str, str]:
    config = payload.model_dump()
    config["auth_value"] = normalize_auth_value(config["auth_value"])
    config["cloud_path"] = normalize_cloud_path_display(config["cloud_path"])
    state.update_config(config)
    runtime.reload()
    state.log("info", "全局同步配置已更新")
    return {"status": "ok"}


def make_cloud_service() -> Cloud115Service:
    config = state.get_config()
    cloud = Cloud115Service(
        auth_value=config["auth_value"],
        cookies_path=app_paths.cookies_path,
    )
    if not cloud.configured():
        raise HTTPException(status_code=400, detail="请先在设置中配置 115 Cookie")
    return cloud


def open_directory_picker(initial_path: str | None = None) -> str:
    if is_docker():
        raise HTTPException(status_code=400, detail="Docker 环境不支持桌面目录选择器")
    if os.name != "nt" and not os.getenv("DISPLAY"):
        raise HTTPException(status_code=400, detail="当前环境没有桌面显示，无法打开目录选择器")
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"无法加载桌面目录选择器: {exc}") from exc

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    selected = filedialog.askdirectory(
        initialdir=initial_path if initial_path and Path(initial_path).exists() else None,
        mustexist=True,
        title="选择本地同步目录",
    )
    root.destroy()
    if not selected:
        raise HTTPException(status_code=400, detail="未选择目录")
    return selected


@app.post("/api/system/pick-local-directory")
async def api_pick_local_directory(initial_path: str | None = Query(default=None)) -> dict[str, str]:
    return {"path": open_directory_picker(initial_path)}


@app.get("/api/cloud/directories")
async def api_cloud_directories(parent_id: str = Query(default="0")) -> dict[str, Any]:
    cloud = make_cloud_service()
    try:
        dirs = [
            {"id": str(entry.remote_id), "name": entry.name}
            for entry in cloud.list_directory(parent_id)
            if entry.is_dir
        ]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dirs.sort(key=lambda item: item["name"].lower())
    return {"parent_id": parent_id, "directories": dirs}


@app.post("/api/run-full-sync")
async def api_run_full_sync() -> dict[str, str]:
    sync_service.request_full_sync("manual")
    return {"status": "ok"}


@app.get("/api/logs")
async def api_logs() -> list[dict[str, Any]]:
    return state.list_logs(limit=200)


@app.get("/api/runtime")
async def api_runtime() -> dict[str, Any]:
    return translated_runtime()

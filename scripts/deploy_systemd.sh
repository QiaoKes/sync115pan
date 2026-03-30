#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="${SERVICE_NAME:-sync115pan}"
SERVICE_PORT="${SYNC115PAN_PORT:-38000}"
SERVICE_HOST="${SYNC115PAN_HOST:-0.0.0.0}"
DATA_DIR="${SYNC115PAN_DATA_DIR:-$PROJECT_ROOT/.data}"
ENV_FILE="$DATA_DIR/systemd.env"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

pick_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    echo "$PYTHON_BIN"
    return
  fi
  if command -v python3.12 >/dev/null 2>&1; then
    echo "python3.12"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  echo "未找到可用的 Python 3.12+ 解释器。" >&2
  exit 1
}

require_python_312() {
  local python_bin="$1"
  "$python_bin" - <<'PY'
import sys
if sys.version_info < (3, 12):
    raise SystemExit("需要 Python 3.12 或更高版本。")
PY
}

detect_service_user() {
  if [[ -n "${SERVICE_USER:-}" ]]; then
    echo "$SERVICE_USER"
    return
  fi
  if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
    echo "$SUDO_USER"
    return
  fi
  id -un
}

detect_service_group() {
  if [[ -n "${SERVICE_GROUP:-}" ]]; then
    echo "$SERVICE_GROUP"
    return
  fi
  id -gn "$1"
}

ensure_root_for_systemd() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "请使用 sudo 运行此脚本，以便写入 systemd unit 并启用服务。" >&2
    exit 1
  fi
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "缺少必要命令: $command_name" >&2
    exit 1
  fi
}

write_env_file() {
  mkdir -p "$DATA_DIR"
  if [[ -f "$ENV_FILE" ]]; then
    return
  fi
  cat >"$ENV_FILE" <<EOF
SYNC115PAN_HOST=$SERVICE_HOST
SYNC115PAN_PORT=$SERVICE_PORT
SYNC115PAN_DATA_DIR=$DATA_DIR
EOF
}

install_python_env() {
  local service_user="$1"
  local python_bin="$2"
  if [[ ! -d "$PROJECT_ROOT/.venv" ]]; then
    sudo -u "$service_user" "$python_bin" -m venv "$PROJECT_ROOT/.venv"
  fi
  sudo -u "$service_user" "$PROJECT_ROOT/.venv/bin/python" -m pip install --upgrade pip
  sudo -u "$service_user" "$PROJECT_ROOT/.venv/bin/pip" install -e "$PROJECT_ROOT"
}

write_unit_file() {
  local service_user="$1"
  local service_group="$2"
  cat >"$UNIT_FILE" <<EOF
[Unit]
Description=sync115pan
After=network.target

[Service]
Type=simple
User=$service_user
Group=$service_group
WorkingDirectory=$PROJECT_ROOT
EnvironmentFile=$ENV_FILE
ExecStart=$PROJECT_ROOT/.venv/bin/python -m sync115pan
Restart=always
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
}

main() {
  ensure_root_for_systemd
  require_command systemctl
  require_command git

  local python_bin
  python_bin="$(pick_python)"
  require_python_312 "$python_bin"

  local service_user
  service_user="$(detect_service_user)"
  local service_group
  service_group="$(detect_service_group "$service_user")"

  mkdir -p "$DATA_DIR"
  chown -R "$service_user:$service_group" "$DATA_DIR"
  chown -R "$service_user:$service_group" "$PROJECT_ROOT"

  write_env_file
  install_python_env "$service_user" "$python_bin"
  write_unit_file "$service_user" "$service_group"

  systemctl daemon-reload
  systemctl enable --now "$SERVICE_NAME"

  cat <<EOF
部署完成。

服务名: $SERVICE_NAME
运行用户: $service_user
项目目录: $PROJECT_ROOT
数据目录: $DATA_DIR
环境文件: $ENV_FILE

常用命令:
  sudo systemctl status $SERVICE_NAME
  sudo systemctl restart $SERVICE_NAME
  sudo journalctl -u $SERVICE_NAME -f

Web 界面:
  http://<NAS-IP>:$SERVICE_PORT
EOF
}

main "$@"

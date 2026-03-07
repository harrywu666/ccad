#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
FRONTEND_DIR="$ROOT_DIR/cad-review-frontend"
BACKEND_DIR="$ROOT_DIR/cad-review-backend"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_LOG="$RUN_DIR/frontend.log"
BACKEND_LOG="$RUN_DIR/backend.log"

mkdir -p "$RUN_DIR"

is_pid_alive() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

read_pid() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    tr -d '[:space:]' < "$pid_file"
  fi
}

ensure_port_free() {
  local port="$1"
  local conflict
  conflict="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$conflict" ]]; then
    echo "port $port is already in use by PID(s): $conflict" >&2
    exit 1
  fi
}

wait_for_http() {
  local url="$1"
  local name="$2"
  for _ in $(seq 1 40); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  echo "$name did not become ready: $url" >&2
  return 1
}

spawn_detached() {
  local cwd="$1"
  local log_file="$2"
  shift 2

  python3 - "$cwd" "$log_file" "$@" <<'PY'
import os
import subprocess
import sys

cwd = sys.argv[1]
log_file = sys.argv[2]
command = sys.argv[3:]

with open(log_file, "ab", buffering=0) as log_handle:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

print(process.pid)
PY
}

start_backend() {
  local pid
  pid="$(read_pid "$BACKEND_PID_FILE")"
  if is_pid_alive "$pid"; then
    echo "backend already running on PID $pid"
    return 0
  fi

  ensure_port_free 7002
  : > "$BACKEND_LOG"
  spawn_detached "$BACKEND_DIR" "$BACKEND_LOG" \
    ./venv/bin/uvicorn main:app --host 127.0.0.1 --port 7002 > "$BACKEND_PID_FILE"
  wait_for_http "http://127.0.0.1:7002/api/health" "backend"
  echo "backend started"
}

start_frontend() {
  local pid
  pid="$(read_pid "$FRONTEND_PID_FILE")"
  if is_pid_alive "$pid"; then
    echo "frontend already running on PID $pid"
    return 0
  fi

  ensure_port_free 7001
  : > "$FRONTEND_LOG"
  spawn_detached "$FRONTEND_DIR" "$FRONTEND_LOG" \
    npm run dev -- --host 127.0.0.1 --port 7001 > "$FRONTEND_PID_FILE"
  wait_for_http "http://127.0.0.1:7001/" "frontend"
  echo "frontend started"
}

start_backend
start_frontend

echo
echo "frontend: http://127.0.0.1:7001"
echo "backend:  http://127.0.0.1:7002/api/health"

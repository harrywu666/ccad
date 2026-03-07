#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"

show_service() {
  local name="$1"
  local pid_file="$2"
  local port="$3"
  local url="$4"

  local pid=""
  if [[ -f "$pid_file" ]]; then
    pid="$(tr -d '[:space:]' < "$pid_file")"
  fi

  echo "[$name]"
  echo "pid file: ${pid_file}"
  echo "pid: ${pid:-none}"

  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "process: alive"
  else
    echo "process: down"
  fi

  if lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "port $port: listening"
  else
    echo "port $port: closed"
  fi

  if curl -fsS "$url" >/dev/null 2>&1; then
    echo "http: ok ($url)"
  else
    echo "http: failed ($url)"
  fi
  echo
}

show_service "frontend" "$FRONTEND_PID_FILE" "7001" "http://127.0.0.1:7001/"
show_service "backend" "$BACKEND_PID_FILE" "7002" "http://127.0.0.1:7002/api/health"

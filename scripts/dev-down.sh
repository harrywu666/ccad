#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"

kill_pid_file() {
  local pid_file="$1"
  local name="$2"
  if [[ ! -f "$pid_file" ]]; then
    echo "$name not running (no pid file)"
    return 0
  fi

  local pid
  pid="$(tr -d '[:space:]' < "$pid_file")"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 0.2
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    echo "$name stopped"
  else
    echo "$name already stopped"
  fi
  rm -f "$pid_file"
}

kill_pid_file "$FRONTEND_PID_FILE" "frontend"
kill_pid_file "$BACKEND_PID_FILE" "backend"

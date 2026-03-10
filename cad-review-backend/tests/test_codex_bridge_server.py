from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib import request


ROOT_DIR = Path(__file__).resolve().parents[2]
BRIDGE_DIR = ROOT_DIR / "codex-bridge"


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


@contextmanager
def _bridge_server():
    port = _free_port()
    env = {
        **os.environ,
        "CODEX_BRIDGE_PORT": str(port),
        "CODEX_BRIDGE_FAKE_MODE": "1",
    }
    process = subprocess.Popen(
        ["npx", "tsx", "src/server.ts"],
        cwd=BRIDGE_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"

    try:
        deadline = time.time() + 8
        while time.time() < deadline:
            if process.poll() is not None:
                break
            try:
                with request.urlopen(f"{base_url}/health", timeout=0.5) as response:
                    if response.status == 200:
                        yield base_url
                        return
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("codex bridge server did not become ready")
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def _post_turn(base_url: str, *, op: str, subsession_key: str) -> dict[str, str]:
    payload = json.dumps(
        {
            "op": op,
            "request_id": f"req-{time.time_ns()}",
            "payload": {
                "subsession_key": subsession_key,
                "input": "say ok",
            },
        }
    ).encode("utf-8")
    req = request.Request(
        f"{base_url}/v1/bridge/turn",
        data=payload,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=5) as response:
        lines = [
            json.loads(line)
            for line in response.read().decode("utf-8").splitlines()
            if line.strip()
        ]
    done = next(item for item in reversed(lines) if item.get("type") == "done")
    return done["payload"]


def test_codex_bridge_can_create_and_reuse_thread():
    with _bridge_server() as base_url:
        first = _post_turn(base_url, op="start_turn", subsession_key="dimension:sheet-a")
        second = _post_turn(base_url, op="start_turn", subsession_key="dimension:sheet-a")

    assert first["thread_id"]
    assert second["thread_id"] == first["thread_id"]

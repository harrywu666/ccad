from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
BRIDGE_DIR = ROOT_DIR / "codex-bridge"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


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

    try:
        deadline = time.time() + 8
        base_url = f"http://127.0.0.1:{port}"
        while time.time() < deadline:
            if process.poll() is not None:
                break
            try:
                import urllib.request

                with urllib.request.urlopen(f"{base_url}/health", timeout=0.5) as response:
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


def test_codex_bridge_client_translates_bridge_events_to_provider_events():
    from services.audit_runtime.codex_bridge_client import CodexBridgeClient

    with _bridge_server() as base_url:
        client = CodexBridgeClient(base_url=base_url)
        result = asyncio.run(
            client.stream_turn(
                op="start_turn",
                subsession_key="planner:root",
                input_text="say ok",
            )
        )

    events = result.events

    assert events[0].event_kind == "provider_stream_delta"

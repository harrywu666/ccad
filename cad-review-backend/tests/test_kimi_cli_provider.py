from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.providers.kimi_cli_provider import KimiCliProvider
from services.audit_runtime.runner_types import RunnerSubsession, RunnerTurnRequest


class _FakeStream:
    def __init__(self, lines: list[str]):
        self._lines = [line.encode("utf-8") for line in lines]

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)


class _FakeProcess:
    def __init__(self, lines: list[str], returncode: int = 0):
        self.stdout = _FakeStream(lines)
        self.stderr = _FakeStream([])
        self.returncode = returncode

    async def wait(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 1


def test_cli_provider_reads_stream_lines_from_process_stdout(monkeypatch):
    captured_chunks: list[str] = []

    async def fake_create_subprocess_exec(*cmd, **kwargs):  # noqa: ANN001
        return _FakeProcess(
            [
                '{"type":"assistant_delta","text":"你好"}\n',
                '{"type":"assistant_delta","text":"继续输出"}\n',
                '{"type":"done"}\n',
            ]
        )

    provider = KimiCliProvider(binary="kimi")
    request = RunnerTurnRequest(
        agent_key="master_planner_agent",
        agent_name="总控规划Agent",
        step_key="task_planning",
        progress_hint=18,
        turn_kind="planning",
        system_prompt="sys",
        user_prompt="user",
    )
    subsession = RunnerSubsession(
        project_id="proj-cli",
        audit_version=1,
        agent_key="master_planner_agent",
        session_key="proj-cli:1:master",
        shared_context={},
    )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    async def on_event(event):  # noqa: ANN001
        if event.event_kind == "provider_stream_delta":
            captured_chunks.append(event.text)

    result = asyncio.run(
        provider.run_stream(
            request,
            subsession,
            on_event=on_event,
        )
    )

    assert captured_chunks == ["你好", "继续输出"]
    assert result.raw_output == "你好继续输出"

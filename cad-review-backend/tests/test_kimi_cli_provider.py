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

    async def read(self, n: int = -1) -> bytes:
        if not self._lines:
            return b""
        if n is None or n < 0:
            data = b"".join(self._lines)
            self._lines = []
            return data
        chunk = self._lines[0]
        if len(chunk) <= n:
            return self._lines.pop(0)
        self._lines[0] = chunk[n:]
        return chunk[:n]


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


def test_cli_provider_decodes_real_stream_json_payload(monkeypatch):
    captured_chunks: list[str] = []

    async def fake_create_subprocess_exec(*cmd, **kwargs):  # noqa: ANN001
        return _FakeProcess(
            [
                '{"role":"assistant","content":[{"type":"think","think":"先想一下"},{"type":"text","text":"ok"}]}\n',
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

    result = asyncio.run(provider.run_stream(request, subsession, on_event=on_event))

    assert captured_chunks == ["ok"]
    assert result.raw_output == "ok"


def test_cli_provider_includes_temp_image_paths_in_prompt(monkeypatch):
    captured_cmd: list[str] = []

    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
        b"\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
        b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    async def fake_create_subprocess_exec(*cmd, **kwargs):  # noqa: ANN001
        captured_cmd[:] = [str(part) for part in cmd]
        return _FakeProcess(
            [
                '{"role":"assistant","content":[{"type":"text","text":"[]"}]}\n',
            ]
        )

    provider = KimiCliProvider(binary="kimi")
    request = RunnerTurnRequest(
        agent_key="relationship_review_agent",
        agent_name="关系审查Agent",
        step_key="relationship_discovery",
        progress_hint=12,
        turn_kind="relationship_review",
        system_prompt="sys",
        user_prompt="user",
        images=[png_bytes],
    )
    subsession = RunnerSubsession(
        project_id="proj-cli",
        audit_version=1,
        agent_key="relationship_review_agent",
        session_key="proj-cli:1:relationship",
        shared_context={},
    )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    asyncio.run(provider.run_stream(request, subsession))

    prompt = captured_cmd[captured_cmd.index("--prompt") + 1]
    assert "请先读取这些图片文件" in prompt
    assert ".png" in prompt


def test_cli_provider_handles_large_single_line_payload(monkeypatch):
    big_text = "a" * 70000

    async def fake_create_subprocess_exec(*cmd, **kwargs):  # noqa: ANN001
        return _FakeProcess(
            [
                '{"role":"assistant","content":[{"type":"text","text":"'
                + big_text
                + '"}]}\n'
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

    result = asyncio.run(provider.run_stream(request, subsession))

    assert result.raw_output == big_text

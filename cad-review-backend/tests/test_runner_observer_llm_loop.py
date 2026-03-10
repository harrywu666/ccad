from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.codex_bridge_client import CodexBridgeTurnResult
from services.audit_runtime.runner_observer_feed import build_observer_snapshot
from services.audit_runtime.runner_observer_types import RunnerObserverMemory


class _FakeText:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeSession:
    def __init__(self, messages) -> None:  # noqa: ANN001
        self._messages = list(messages)

    def prompt(self, prompt_input, merge_wire_messages=True):  # noqa: ANN001
        async def _stream():
            for message in self._messages:
                yield message

        return _stream()

    async def cancel(self) -> None:
        return None

    async def close(self) -> None:
        return None


def test_kimi_sdk_provider_can_observe_once_via_llm_json():
    from services.audit_runtime.providers.kimi_sdk_provider import KimiSdkProvider

    async def _fake_session_factory(**kwargs):  # noqa: ANN001
        return _FakeSession(
            [
                _FakeText(
                    '{"summary":"当前流程正常推进","risk_level":"low","suggested_action":"observe_only","reason":"最近一直有新输出","should_intervene":false,"confidence":0.88,"user_facing_broadcast":"Runner 正在继续观察当前流程"}'
                )
            ]
        )

    provider = KimiSdkProvider(session_factory=_fake_session_factory)
    snapshot = build_observer_snapshot(
        project_id="proj-llm-observer",
        audit_version=1,
        runtime_status={"status": "running", "current_step": "尺寸复核"},
        recent_events=[{"event_kind": "runner_broadcast", "message": "Runner 正在继续观察"}],
    )
    memory = RunnerObserverMemory(project_id="proj-llm-observer", audit_version=1)

    decision = asyncio.run(provider.observe_once(snapshot, memory))

    assert decision.suggested_action == "observe_only"
    assert decision.user_facing_broadcast == "Runner 正在继续观察当前流程"


def test_codex_sdk_provider_can_observe_once_via_bridge_json():
    from services.audit_runtime.providers.codex_sdk_provider import CodexSdkProvider

    class _FakeBridgeClient:
        async def stream_turn(self, **kwargs):  # noqa: ANN001
            return CodexBridgeTurnResult(
                output_text='{"summary":"当前流程正常推进","risk_level":"low","suggested_action":"observe_only","reason":"最近一直有新输出","should_intervene":false,"confidence":0.76,"user_facing_broadcast":"Runner 正在继续观察当前流程"}',
                status="ok",
                thread_id="thread-observer-1",
            )

    provider = CodexSdkProvider(bridge_client=_FakeBridgeClient())
    snapshot = build_observer_snapshot(
        project_id="proj-codex-observer",
        audit_version=2,
        runtime_status={"status": "running", "current_step": "关系复核"},
        recent_events=[{"event_kind": "runner_turn_started", "message": "关系复核开始"}],
    )
    memory = RunnerObserverMemory(project_id="proj-codex-observer", audit_version=2)

    decision = asyncio.run(provider.observe_once(snapshot, memory))

    assert decision.suggested_action == "observe_only"
    assert decision.user_facing_broadcast == "Runner 正在继续观察当前流程"

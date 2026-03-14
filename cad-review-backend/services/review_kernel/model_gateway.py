"""审图内核模型网关：统一 kimi sdk / openrouter 调用。"""

from __future__ import annotations

import ast
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from uuid import uuid4

from services.ai_service import call_kimi
from services.review_kernel.policy import ProjectPolicy


JsonPayload = dict[str, Any] | list[dict[str, Any]]


@dataclass(slots=True)
class InferenceRequest:
    system_prompt: str
    user_prompt: str
    max_tokens: int
    temperature: float = 0.0
    agent_type: str = "review_kernel"
    images: list[bytes] = field(default_factory=list)


@dataclass(slots=True)
class InferenceResponse:
    content: JsonPayload
    provider: str
    model: str | None = None
    raw_output: str = ""


class ModelGateway(ABC):
    provider_name: str = "unknown"

    @abstractmethod
    async def multimodal_infer(self, request: InferenceRequest) -> InferenceResponse: ...


def _parse_json_like(raw: str) -> JsonPayload:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("empty_llm_output")

    def _try_parse(candidate: str) -> Optional[JsonPayload]:
        value = candidate.strip()
        if not value:
            return None
        try:
            loaded = json.loads(value)
            if isinstance(loaded, (dict, list)):
                return loaded
        except json.JSONDecodeError:
            pass
        try:
            loaded = ast.literal_eval(value)
            if isinstance(loaded, (dict, list)):
                return loaded
        except Exception:
            pass
        return None

    parsed = _try_parse(text)
    if parsed is not None:
        return parsed

    fenced = text
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            parsed = _try_parse(part.replace("json", "", 1))
            if parsed is not None:
                return parsed
        fenced = parts[-1]

    left, right = fenced.find("{"), fenced.rfind("}")
    if left != -1 and right > left:
        parsed = _try_parse(fenced[left : right + 1])
        if parsed is not None:
            return parsed

    left, right = fenced.find("["), fenced.rfind("]")
    if left != -1 and right > left:
        parsed = _try_parse(fenced[left : right + 1])
        if parsed is not None:
            return parsed

    raise ValueError(f"invalid_json_like_output:{text[:120]}")


class OpenRouterGateway(ModelGateway):
    provider_name = "openrouter"

    def __init__(self, *, run_once_func=call_kimi) -> None:  # noqa: ANN001
        self._run_once_func = run_once_func

    async def multimodal_infer(self, request: InferenceRequest) -> InferenceResponse:
        output = await self._run_once_func(
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
            images=request.images,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            provider_override="openrouter",
        )
        if not isinstance(output, (dict, list)):
            raise RuntimeError("openrouter_output_not_json")
        return InferenceResponse(
            content=output,
            provider=self.provider_name,
            model=str(os.getenv("OPENROUTER_MODEL") or "openrouter/healer-alpha"),
        )


class KimiSdkGateway(ModelGateway):
    provider_name = "kimi_sdk"

    def __init__(
        self,
        *,
        provider_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._provider_factory = provider_factory
        self._provider = None

    def _default_provider_factory(self) -> Any:
        try:
            from services.audit_runtime.providers.kimi_sdk_provider import KimiSdkProvider
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"kimi_sdk_provider_unavailable:{exc}") from exc
        return KimiSdkProvider()

    def _ensure_provider(self) -> Any:
        if self._provider is None:
            factory = self._provider_factory or self._default_provider_factory
            self._provider = factory()
        return self._provider

    async def multimodal_infer(self, request: InferenceRequest) -> InferenceResponse:
        from services.audit_runtime.runner_types import RunnerSubsession, RunnerTurnRequest

        provider = self._ensure_provider()
        turn_request = RunnerTurnRequest(
            agent_key=request.agent_type,
            turn_kind="review_kernel_llm",
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
            images=request.images,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            agent_name=request.agent_type,
            step_key="review_kernel_llm",
            progress_hint=None,
            meta={},
        )
        subsession = RunnerSubsession(
            project_id="review-kernel",
            audit_version=0,
            agent_key=request.agent_type,
            session_key=f"rk-{uuid4().hex[:12]}",
            shared_context={},
        )
        result = await provider.run_once(turn_request, subsession)
        output = result.output
        if isinstance(output, (dict, list)):
            return InferenceResponse(
                content=output,
                provider=self.provider_name,
                model=None,
                raw_output=str(result.raw_output or ""),
            )

        raw_output = str(result.raw_output or output or "").strip()
        parsed = _parse_json_like(raw_output)
        return InferenceResponse(
            content=parsed,
            provider=self.provider_name,
            model=None,
            raw_output=raw_output,
        )


def build_model_gateway(
    policy: ProjectPolicy,
    *,
    openrouter_run_once=call_kimi,  # noqa: ANN001
    kimi_sdk_provider_factory: Optional[Callable[[], Any]] = None,
) -> ModelGateway:
    provider = str(policy.llm_provider or "").strip().lower()
    if provider == "kimi_sdk":
        return KimiSdkGateway(provider_factory=kimi_sdk_provider_factory)
    if provider == "openrouter":
        return OpenRouterGateway(run_once_func=openrouter_run_once)
    raise ValueError(f"unsupported_llm_provider:{provider}")


__all__ = [
    "InferenceRequest",
    "InferenceResponse",
    "ModelGateway",
    "KimiSdkGateway",
    "OpenRouterGateway",
    "build_model_gateway",
]

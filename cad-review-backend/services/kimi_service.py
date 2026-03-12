"""
Kimi API 服务模块
提供统一的Kimi API调用接口，支持图片识别和文本处理
"""

import os
import re
import json
import ast
import base64
import logging
import asyncio
import inspect
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from services.audit_runtime.cancel_registry import AuditCancellationRequested

logger = logging.getLogger(__name__)

KIMI_CODE_API_BASE = "https://api.kimi.com/coding/v1"
KIMI_CODE_MODEL = "k2p5"
KIMI_OFFICIAL_API_BASE = "https://api.moonshot.cn/v1"
KIMI_OFFICIAL_MODEL = "kimi-k2.5"
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "openrouter/healer-alpha"
KIMI_UA = "claude-code/1.0"


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _http_timeout_config():
    import httpx

    connect_timeout = _env_float("KIMI_CONNECT_TIMEOUT_SECONDS", 30.0)
    read_timeout = _env_float("KIMI_READ_TIMEOUT_SECONDS", 600.0)
    write_timeout = _env_float("KIMI_WRITE_TIMEOUT_SECONDS", 60.0)
    pool_timeout = _env_float("KIMI_POOL_TIMEOUT_SECONDS", 30.0)
    return httpx.Timeout(
        connect=connect_timeout,
        read=read_timeout,
        write=write_timeout,
        pool=pool_timeout,
    )


def _provider() -> str:
    raw = (os.getenv("KIMI_PROVIDER", "official") or "official").strip().lower()
    if raw in {"official", "moonshot", "openai"}:
        return "official"
    if raw in {"openrouter", "open_router"}:
        return "openrouter"
    return "code"


def _resolve_api_key() -> str:
    provider = _provider()
    if provider == "openrouter":
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise ValueError("未设置 OPENROUTER_API_KEY 环境变量")
        return key
    if provider == "official":
        key = (
            os.getenv("KIMI_OFFICIAL_API_KEY", "").strip()
            or os.getenv("MOONSHOT_API_KEY", "").strip()
        )
        if not key:
            raise ValueError("未设置 KIMI_OFFICIAL_API_KEY 或 MOONSHOT_API_KEY 环境变量")
        return key

    key = os.getenv("KIMI_CODE_API_KEY", "").strip()
    if not key:
        raise ValueError("未设置 KIMI_CODE_API_KEY 环境变量")
    return key


def _headers() -> dict:
    """构建API请求头"""
    key = _resolve_api_key()
    provider = _provider()
    if provider in {"official", "openrouter"}:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": KIMI_UA,
        }
        if provider == "openrouter":
            referer = os.getenv("OPENROUTER_HTTP_REFERER", "").strip()
            title = os.getenv("OPENROUTER_X_TITLE", "").strip()
            if referer:
                headers["HTTP-Referer"] = referer
            if title:
                headers["X-OpenRouter-Title"] = title
        return headers
    return {
        "Content-Type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "User-Agent": KIMI_UA,
    }


def _mime(data: bytes) -> str:
    """根据文件头自动判断图片格式"""
    b = base64.b64encode(data[:4]).decode()
    if b.startswith("iVBOR"):
        return "image/png"
    if b.startswith("R0lGO"):
        return "image/gif"
    if b.startswith("UklGR"):
        return "image/webp"
    return "image/jpeg"


def _base64_data_url(data: bytes) -> str:
    return f"data:{_mime(data)};base64,{base64.b64encode(data).decode()}"


def _official_temperature(requested: float) -> float:
    raw = os.getenv("KIMI_OFFICIAL_TEMPERATURE", "").strip()
    if raw:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    # kimi-k2.5 官方兼容接口当前仅接受 1
    return 1.0


def _retryable_status(status_code: int) -> bool:
    return status_code in {429, 500, 502, 503, 504}


def _retry_sleep_seconds(attempt: int, response: Any = None) -> float:
    retry_after = None
    if response is not None:
        headers = getattr(response, "headers", None)
        if headers:
            retry_after = headers.get("Retry-After")
    if retry_after:
        try:
            seconds = float(str(retry_after).strip())
            if seconds > 0:
                return seconds
        except (TypeError, ValueError):
            pass

    base = _env_float("KIMI_RETRY_BASE_SECONDS", 2.0)
    cap = _env_float("KIMI_RETRY_MAX_SECONDS", 20.0)
    return min(cap, base * max(1, attempt))


def _build_kimi_request(
    system_prompt: str,
    user_prompt: str,
    images: Optional[List[bytes]],
    temperature: float,
    max_tokens: int,
    *,
    stream: bool = False,
) -> tuple[str, dict[str, Any], str]:
    provider = _provider()
    if provider in {"official", "openrouter"}:
        content: List[dict[str, Any]] = []
        for img in (images or []):
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": _base64_data_url(img),
                },
            })
        content.append({"type": "text", "text": user_prompt})
        payload: dict[str, Any] = {
            "model": os.getenv(
                "OPENROUTER_MODEL",
                OPENROUTER_MODEL,
            ) if provider == "openrouter" else os.getenv("KIMI_OFFICIAL_MODEL", KIMI_OFFICIAL_MODEL),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "temperature": temperature if provider == "openrouter" else _official_temperature(temperature),
            "max_tokens": max_tokens,
        }
        if provider == "openrouter" and os.getenv("OPENROUTER_REASONING_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}:
            payload["reasoning"] = {"enabled": True}
        if stream:
            payload["stream"] = True
        base_url = os.getenv("OPENROUTER_API_BASE", OPENROUTER_API_BASE) if provider == "openrouter" else os.getenv("KIMI_OFFICIAL_API_BASE", KIMI_OFFICIAL_API_BASE)
        endpoint = f"{base_url.rstrip('/')}/chat/completions"
        return provider, payload, endpoint

    content = []
    for img in (images or []):
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": _mime(img),
                "data": base64.b64encode(img).decode(),
            },
        })
    content.append({"type": "text", "text": user_prompt})
    payload = {
        "model": os.getenv("KIMI_CODE_MODEL", KIMI_CODE_MODEL),
        "system": system_prompt,
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if stream:
        payload["stream"] = True
    endpoint = f"{os.getenv('KIMI_CODE_API_BASE', KIMI_CODE_API_BASE).rstrip('/')}/messages"
    return provider, payload, endpoint


def _extract_response_text(provider: str, data: dict[str, Any]) -> str:
    if provider in {"official", "openrouter"}:
        return data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
    return "".join(
        b.get("text", "")
        for b in data.get("content", [])
        if b.get("type") == "text"
    )


def _extract_stream_delta(provider: str, payload: dict[str, Any]) -> str:
    if provider in {"official", "openrouter"}:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        delta = choices[0].get("delta")
        if not isinstance(delta, dict):
            return ""
        content = delta.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
            return "".join(parts)
        return ""
    content = payload.get("delta") or payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


async def _emit_delta(
    on_delta: Optional[Callable[[str], Optional[Awaitable[None]]]],
    chunk: str,
) -> None:
    if not on_delta or not chunk:
        return
    result = on_delta(chunk)
    if inspect.isawaitable(result):
        await result


async def _emit_retry(
    on_retry: Optional[Callable[[Dict[str, Any]], Optional[Awaitable[None]]]],
    payload: Dict[str, Any],
) -> None:
    if not on_retry:
        return
    result = on_retry(payload)
    if inspect.isawaitable(result):
        await result


def _stream_idle_timeout_seconds() -> float:
    return _env_float("KIMI_STREAM_IDLE_TIMEOUT_SECONDS", 30.0)


def _raise_if_stream_cancelled(
    should_cancel: Optional[Callable[[], bool]],
) -> None:
    if should_cancel and should_cancel():
        raise AuditCancellationRequested("用户手动中断审核")


def _parse_json(text: str) -> Union[dict, list]:
    """健壮的 JSON 提取：直接解析 → 剥离代码块 → 暴力搜索"""
    t = text.strip()

    def try_load(candidate: str) -> Union[dict, list, None]:
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

    parsed = try_load(t)
    if parsed is not None:
        return parsed

    m = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", t)
    if m:
        parsed = try_load(m.group(1))
        if parsed is not None:
            return parsed

    a, b = t.find("{"), t.rfind("}")
    if a != -1 and b > a:
        parsed = try_load(t[a:b + 1])
        if parsed is not None:
            return parsed

    a, b = t.find("["), t.rfind("]")
    if a != -1 and b > a:
        parsed = try_load(t[a:b + 1])
        if parsed is not None:
            return parsed

    raise ValueError(f"无法提取 JSON，原文前500字：{text[:500]}")


async def call_kimi(
    system_prompt: str,
    user_prompt: str,
    images: List[bytes] = None,
    temperature: float = 0.1,
    max_tokens: int = 65536,
) -> Union[dict, list]:
    """
    统一 Kimi 调用入口（支持纯文本和多图混合）
    
    Args:
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        images: 图片 bytes 列表，None 或空列表表示纯文本请求
        temperature: 温度参数
    
    Returns:
        解析后的 JSON 对象或列表
    """
    import httpx
    max_retries = _env_int("KIMI_MAX_RETRIES", 3)

    provider, payload, endpoint = _build_kimi_request(
        system_prompt,
        user_prompt,
        images,
        temperature,
        max_tokens,
    )
    
    async with httpx.AsyncClient(timeout=_http_timeout_config(), trust_env=False) as client:
        for attempt in range(max_retries + 1):
            try:
                resp = await client.post(
                    endpoint,
                    headers=_headers(),
                    json=payload,
                )
            except httpx.TimeoutException as exc:
                if attempt >= max_retries:
                    raise RuntimeError(f"Kimi API 超时: {exc}") from exc
                delay = _retry_sleep_seconds(attempt + 1)
                logger.warning(
                    "Kimi 请求超时，第 %d 次重试前等待 %.1f 秒",
                    attempt + 1,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            except httpx.HTTPError as exc:
                if attempt >= max_retries:
                    raise RuntimeError(f"Kimi API 网络错误: {exc}") from exc
                delay = _retry_sleep_seconds(attempt + 1)
                logger.warning(
                    "Kimi 网络异常，第 %d 次重试前等待 %.1f 秒",
                    attempt + 1,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            if resp.status_code == 200:
                break

            if not _retryable_status(resp.status_code) or attempt >= max_retries:
                raise RuntimeError(f"Kimi API 失败 ({resp.status_code}): {resp.text[:300]}")

            delay = _retry_sleep_seconds(attempt + 1, resp)
            logger.warning(
                "Kimi 服务暂时繁忙（%s），第 %d 次重试前等待 %.1f 秒",
                resp.status_code,
                attempt + 1,
                delay,
            )
            await asyncio.sleep(delay)

    data = resp.json()
    raw = _extract_response_text(provider, data)
    logger.info("Kimi 响应长度: %d 字符", len(raw))
    return _parse_json(raw)


async def call_kimi_stream(
    system_prompt: str,
    user_prompt: str,
    images: List[bytes] = None,
    temperature: float = 0.1,
    max_tokens: int = 65536,
    on_delta: Optional[Callable[[str], Optional[Awaitable[None]]]] = None,
    on_retry: Optional[Callable[[Dict[str, Any]], Optional[Awaitable[None]]]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Union[dict, list]:
    import httpx

    max_retries = _env_int("KIMI_MAX_RETRIES", 3)
    idle_timeout = _stream_idle_timeout_seconds()
    provider, payload, endpoint = _build_kimi_request(
        system_prompt,
        user_prompt,
        images,
        temperature,
        max_tokens,
        stream=True,
    )

    async with httpx.AsyncClient(timeout=_http_timeout_config(), trust_env=False) as client:
        for attempt in range(max_retries + 1):
            chunks: List[str] = []
            try:
                _raise_if_stream_cancelled(should_cancel)
                async with client.stream(
                    "POST",
                    endpoint,
                    headers=_headers(),
                    json=payload,
                ) as resp:
                    if resp.status_code != 200:
                        if not _retryable_status(resp.status_code) or attempt >= max_retries:
                            text = getattr(resp, "text", "") or ""
                            raise RuntimeError(f"Kimi API 失败 ({resp.status_code}): {text[:300]}")
                        delay = _retry_sleep_seconds(attempt + 1, resp)
                        logger.warning(
                            "Kimi 流式服务暂时繁忙（%s），第 %d 次重试前等待 %.1f 秒",
                            resp.status_code,
                            attempt + 1,
                            delay,
                        )
                        await _emit_retry(
                            on_retry,
                            {
                                "attempt": attempt + 1,
                                "status_code": resp.status_code,
                                "delay_seconds": delay,
                                "reason": "retryable_status",
                            },
                        )
                        await asyncio.sleep(delay)
                        continue

                    iterator = resp.aiter_lines().__aiter__()
                    while True:
                        _raise_if_stream_cancelled(should_cancel)
                        try:
                            line = await asyncio.wait_for(iterator.__anext__(), timeout=idle_timeout)
                        except StopAsyncIteration:
                            break
                        except asyncio.TimeoutError as exc:
                            if attempt >= max_retries:
                                raise RuntimeError(
                                    f"Kimi 流式长时间没有新内容（>{idle_timeout:.1f} 秒）"
                                ) from exc
                            delay = _retry_sleep_seconds(attempt + 1)
                            logger.warning(
                                "Kimi 流式长时间没有新内容，第 %d 次重试前等待 %.1f 秒",
                                attempt + 1,
                                delay,
                            )
                            await _emit_retry(
                                on_retry,
                                {
                                    "attempt": attempt + 1,
                                    "status_code": None,
                                    "delay_seconds": delay,
                                    "reason": "idle_timeout",
                                },
                            )
                            await asyncio.sleep(delay)
                            break

                        text = (line or "").strip()
                        if not text or not text.startswith("data:"):
                            continue
                        body = text[5:].strip()
                        if not body or body == "[DONE]":
                            continue
                        payload_json = json.loads(body)
                        delta = _extract_stream_delta(provider, payload_json)
                        if not delta:
                            continue
                        chunks.append(delta)
                        await _emit_delta(on_delta, delta)

                    else:
                        pass

                    if attempt < max_retries and not chunks:
                        continue

                raw = "".join(chunks)
                logger.info("Kimi 流式响应长度: %d 字符", len(raw))
                return _parse_json(raw)
            except AuditCancellationRequested:
                raise
            except httpx.TimeoutException as exc:
                if attempt >= max_retries:
                    raise RuntimeError(f"Kimi API 超时: {exc}") from exc
                delay = _retry_sleep_seconds(attempt + 1)
                logger.warning(
                    "Kimi 流式请求超时，第 %d 次重试前等待 %.1f 秒",
                    attempt + 1,
                    delay,
                )
                await _emit_retry(
                    on_retry,
                    {
                        "attempt": attempt + 1,
                        "status_code": None,
                        "delay_seconds": delay,
                        "reason": "timeout",
                    },
                )
                await asyncio.sleep(delay)
            except httpx.HTTPError as exc:
                if attempt >= max_retries:
                    raise RuntimeError(f"Kimi API 网络错误: {exc}") from exc
                delay = _retry_sleep_seconds(attempt + 1)
                logger.warning(
                    "Kimi 流式网络异常，第 %d 次重试前等待 %.1f 秒",
                    attempt + 1,
                    delay,
                )
                await _emit_retry(
                    on_retry,
                    {
                        "attempt": attempt + 1,
                        "status_code": None,
                        "delay_seconds": delay,
                        "reason": "network_error",
                    },
                )
                await asyncio.sleep(delay)

    raise RuntimeError("Kimi 流式调用失败：超过最大重试次数")


async def async_recognize_catalog(image_path: str) -> list:
    """
    识别图纸目录
    
    Args:
        image_path: 目录图片路径
    
    Returns:
        目录条目列表
    """
    from PIL import Image, ImageEnhance
    import io
    
    with open(image_path, "rb") as f:
        image_data = f.read()
    
    img = Image.open(io.BytesIO(image_data)).convert("RGB")

    def to_png_bytes(src: Image.Image, max_width: int = 2200) -> bytes:
        out = src
        if out.width > max_width:
            ratio = max_width / out.width
            out = out.resize((max_width, int(out.height * ratio)), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return buf.getvalue()

    # 目录条目通常集中在左侧表格区域：给Kimi一张放大表格图 + 一张全图做上下文
    left_ratio = 0.46
    left_crop = img.crop((0, 0, int(img.width * left_ratio), img.height))
    if left_crop.width < 1800:
        ratio = 1800 / left_crop.width
        left_crop = left_crop.resize((1800, int(left_crop.height * ratio)), Image.Resampling.LANCZOS)
    left_crop = ImageEnhance.Contrast(left_crop).enhance(1.2)
    left_crop = ImageEnhance.Sharpness(left_crop).enhance(1.2)

    images = [to_png_bytes(left_crop), to_png_bytes(img)]

    from services.ai_prompt_service import resolve_stage_prompts

    prompts = resolve_stage_prompts("catalog_recognition")
    result = await call_kimi(
        system_prompt=prompts["system_prompt"],
        user_prompt=prompts["user_prompt"],
        images=images,
    )
    return result if isinstance(result, list) else []


def recognize_catalog(image_path: str) -> list:
    """
    同步封装：用于非异步调用场景
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(async_recognize_catalog(image_path))
    raise RuntimeError("recognize_catalog 不能在运行中的事件循环内直接调用，请使用 async_recognize_catalog")


def _sanitize_sheet_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_png_bytes(image, max_long_side: int = 2400, min_short_side: int = 1000) -> bytes:
    """控制图片尺寸，平衡识别质量和速度"""
    from PIL import Image
    import io

    out = image.convert("RGB")
    long_side = max(out.width, out.height)
    if long_side > max_long_side:
        ratio = max_long_side / long_side
        out = out.resize((int(out.width * ratio), int(out.height * ratio)), Image.Resampling.LANCZOS)

    short_side = min(out.width, out.height)
    if short_side < min_short_side and short_side > 0:
        ratio = min_short_side / short_side
        out = out.resize((int(out.width * ratio), int(out.height * ratio)), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def _prepare_sheet_crops(image_data: bytes) -> Dict[str, bytes]:
    """裁剪单页图纸的左侧、右侧、下方区域"""
    from PIL import Image, ImageEnhance
    import io

    img = Image.open(io.BytesIO(image_data)).convert("RGB")
    width, height = img.size

    left_crop = img.crop((0, 0, int(width * 0.34), height))
    right_crop = img.crop((int(width * 0.66), 0, width, height))
    bottom_crop = img.crop((0, int(height * 0.66), width, height))

    def enhance(source):
        enhanced = ImageEnhance.Contrast(source).enhance(1.2)
        enhanced = ImageEnhance.Sharpness(enhanced).enhance(1.25)
        return enhanced

    return {
        "left": _to_png_bytes(enhance(left_crop)),
        "right": _to_png_bytes(enhance(right_crop)),
        "bottom": _to_png_bytes(enhance(bottom_crop)),
    }


async def async_recognize_sheet_info(image_data: bytes, page_index: int = 0) -> dict:
    """
    单Agent识别图纸图名图号：将左/右/下三块同时输入同一个Agent
    
    Args:
        image_data: 图纸PNG图片bytes
        page_index: 页码（0-based）
    
    Returns:
        包含图号和图名的字典
    """
    logger.info("页 %s: 开始单Agent识别（输入3块裁剪图）", page_index + 1)
    crops = _prepare_sheet_crops(image_data)
    from services.ai_prompt_service import resolve_stage_prompts

    prompts = resolve_stage_prompts("sheet_recognition")
    result = await call_kimi(
        system_prompt=prompts["system_prompt"],
        user_prompt=prompts["user_prompt"],
        images=[crops["left"], crops["right"], crops["bottom"]],
        temperature=0.0,
    )

    if not isinstance(result, dict):
        logger.warning("页 %s: 单Agent返回非对象，已置空", page_index + 1)
        return {"page_index": page_index, "图号": "", "图名": "", "置信度": 0.0, "依据": "", "raw": {}}

    normalized = {
        "page_index": page_index,
        "图号": _sanitize_sheet_value(result.get("图号") or result.get("sheet_no") or result.get("sheetNo")),
        "图名": _sanitize_sheet_value(result.get("图名") or result.get("sheet_name") or result.get("sheetName")),
        "置信度": _safe_float(result.get("置信度"), 0.0),
        "依据": _sanitize_sheet_value(result.get("依据") or result.get("reason")),
        "raw": result,
    }
    logger.info(
        "页 %s: 单Agent识别完成 图号='%s' 图名='%s' 置信度=%.3f",
        page_index + 1,
        normalized["图号"],
        normalized["图名"],
        normalized["置信度"],
    )
    return normalized


async def async_summarize_sheet_infos(page_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    汇总 Agent：对单Agent识别结果进行统一汇总纠偏
    """
    if not page_results:
        return []
    logger.info("汇总Agent: 开始汇总 %s 页识别结果", len(page_results))

    payload = {
        "pages": [
            {
                "page_index": int(item.get("page_index", -1)),
                "图号": _sanitize_sheet_value(item.get("图号")),
                "图名": _sanitize_sheet_value(item.get("图名")),
                "置信度": _safe_float(item.get("置信度"), 0.0),
                "依据": _sanitize_sheet_value(item.get("依据")),
            }
            for item in page_results
        ]
    }

    from services.ai_prompt_service import resolve_stage_prompts

    prompts = resolve_stage_prompts(
        "sheet_summarization",
        {"payload_json": json.dumps(payload, ensure_ascii=False)},
    )
    result = await call_kimi(
        system_prompt=prompts["system_prompt"],
        user_prompt=prompts["user_prompt"],
        temperature=0.0,
    )

    if not isinstance(result, list):
        logger.warning("汇总Agent: 返回非数组，跳过汇总")
        return []

    normalized: List[Dict[str, Any]] = []
    for item in result:
        if not isinstance(item, dict):
            continue

        page_index = item.get("page_index", -1)
        try:
            page_index = int(page_index)
        except (TypeError, ValueError):
            page_index = -1

        normalized.append(
            {
                "page_index": page_index,
                "图号": _sanitize_sheet_value(item.get("图号") or item.get("sheet_no") or item.get("sheetNo")),
                "图名": _sanitize_sheet_value(item.get("图名") or item.get("sheet_name") or item.get("sheetName")),
                "置信度": _safe_float(item.get("置信度"), 0.0),
                "依据": _sanitize_sheet_value(item.get("理由") or item.get("依据") or item.get("reason")),
            }
        )

    logger.info("汇总Agent: 完成，输出 %s 条", len(normalized))
    return normalized


async def async_validate_sheet_catalog_mapping(
    page_summaries: List[Dict[str, Any]],
    catalog_items: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    """
    校验 Agent：将汇总结果与锁定目录做一对一匹配
    """
    if not page_summaries or not catalog_items:
        return []
    logger.info(
        "校验Agent: 开始一对一校验 pages=%s catalog=%s",
        len(page_summaries),
        len(catalog_items),
    )

    payload = {
        "pages": [
            {
                "page_index": int(item.get("page_index", -1)),
                "图号": _sanitize_sheet_value(item.get("图号")),
                "图名": _sanitize_sheet_value(item.get("图名")),
            }
            for item in page_summaries
        ],
        "catalog": [
            {
                "图号": _sanitize_sheet_value(item.get("sheet_no")),
                "图名": _sanitize_sheet_value(item.get("sheet_name")),
            }
            for item in catalog_items
        ],
    }

    from services.ai_prompt_service import resolve_stage_prompts

    prompts = resolve_stage_prompts(
        "sheet_catalog_validation",
        {"payload_json": json.dumps(payload, ensure_ascii=False)},
    )
    result = await call_kimi(
        system_prompt=prompts["system_prompt"],
        user_prompt=prompts["user_prompt"],
        temperature=0.0,
    )

    if not isinstance(result, list):
        logger.warning("校验Agent: 返回非数组，跳过校验")
        return []

    normalized: List[Dict[str, Any]] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        page_index = item.get("page_index", -1)
        try:
            page_index = int(page_index)
        except (TypeError, ValueError):
            page_index = -1

        normalized.append(
            {
                "page_index": page_index,
                "catalog_sheet_no": _sanitize_sheet_value(
                    item.get("catalog_sheet_no") or item.get("图号") or item.get("sheet_no")
                ),
                "catalog_sheet_name": _sanitize_sheet_value(
                    item.get("catalog_sheet_name") or item.get("图名") or item.get("sheet_name")
                ),
                "置信度": _safe_float(item.get("置信度"), 0.0),
                "理由": _sanitize_sheet_value(item.get("理由") or item.get("reason")),
            }
        )

    logger.info("校验Agent: 完成，输出 %s 条", len(normalized))
    return normalized


def recognize_sheet_info(image_data: bytes) -> dict:
    """
    同步封装：用于非异步调用场景
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(async_recognize_sheet_info(image_data))
    raise RuntimeError("recognize_sheet_info 不能在运行中的事件循环内直接调用，请使用 async_recognize_sheet_info")


async def test_kimi_connection() -> dict:
    """启动时调用，验证 API Key 和网络连通性"""
    try:
        result = await call_kimi(
            system_prompt="You are a test assistant.",
            user_prompt='Return exactly: {"status":"ok"}',
        )
        return {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}

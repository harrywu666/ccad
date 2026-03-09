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
from typing import Any, Dict, List, Union

logger = logging.getLogger(__name__)

KIMI_CODE_API_BASE = "https://api.kimi.com/coding/v1"
KIMI_CODE_MODEL = "k2p5"
KIMI_OFFICIAL_API_BASE = "https://api.moonshot.cn/v1"
KIMI_OFFICIAL_MODEL = "kimi-k2.5"
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
    return "code"


def _resolve_api_key() -> str:
    provider = _provider()
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
    if _provider() == "official":
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": KIMI_UA,
        }
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
    
    provider = _provider()
    if provider == "official":
        content = []
        for img in (images or []):
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": _base64_data_url(img),
                },
            })
        content.append({"type": "text", "text": user_prompt})
        payload = {
            "model": os.getenv("KIMI_OFFICIAL_MODEL", KIMI_OFFICIAL_MODEL),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "temperature": _official_temperature(temperature),
            "max_tokens": max_tokens,
        }
        endpoint = f"{os.getenv('KIMI_OFFICIAL_API_BASE', KIMI_OFFICIAL_API_BASE).rstrip('/')}/chat/completions"
    else:
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
        endpoint = f"{os.getenv('KIMI_CODE_API_BASE', KIMI_CODE_API_BASE).rstrip('/')}/messages"
    
    try:
        async with httpx.AsyncClient(timeout=_http_timeout_config(), trust_env=False) as client:
            resp = await client.post(
                endpoint,
                headers=_headers(),
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"Kimi API 超时: {exc}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Kimi API 网络错误: {exc}") from exc
    
    if resp.status_code != 200:
        raise RuntimeError(f"Kimi API 失败 ({resp.status_code}): {resp.text[:300]}")
    
    data = resp.json()
    if provider == "official":
        raw = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
    else:
        raw = "".join(
            b.get("text", "")
            for b in data.get("content", [])
            if b.get("type") == "text"
        )
    logger.info("Kimi 响应长度: %d 字符", len(raw))
    return _parse_json(raw)


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

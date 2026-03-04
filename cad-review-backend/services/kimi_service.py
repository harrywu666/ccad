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

KIMI_API_BASE = "https://api.kimi.com/coding/v1"
KIMI_MODEL = "k2p5"
KIMI_UA = "claude-code/1.0"


def _headers() -> dict:
    """构建API请求头"""
    key = os.getenv("KIMI_CODE_API_KEY", "")
    if not key:
        raise ValueError("未设置 KIMI_CODE_API_KEY 环境变量")
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
        "model": KIMI_MODEL,
        "system": system_prompt,
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
        "max_tokens": 65536,
    }
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            f"{KIMI_API_BASE}/messages",
            headers=_headers(),
            json=payload,
        )
    
    if resp.status_code != 200:
        raise RuntimeError(f"Kimi API 失败 ({resp.status_code}): {resp.text[:300]}")
    
    data = resp.json()
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

    result = await call_kimi(
        system_prompt="你是室内装饰施工图识别专家，只返回JSON，不要任何解释。",
        user_prompt=(
            "你将收到2张图：第1张是目录表左侧放大图，第2张是全图。"
            "请以第1张为主提取所有目录条目，结合第2张纠正。"
            "只返回JSON数组，不要markdown，不要解释。"
            "每条记录字段固定为：图号、图名、版本、日期。"
            "图号需保留原样（例如 A1-01 / 02.03 / A4.02）。"
            "无法识别的字段填空字符串。"
            "输出示例：[{\"图号\":\"A1-01\",\"图名\":\"平面布置图\",\"版本\":\"A\",\"日期\":\"2026.01\"}]"
        ),
        images=images
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
    result = await call_kimi(
        system_prompt="你是施工图识别Agent，只输出JSON。",
        user_prompt=(
            "你将收到同一页施工图的3张裁剪图：第1张左侧，第2张右侧，第3张下方。"
            "请综合三张图，识别该页唯一的图号和图名。"
            "图号格式不固定，保留原样（如 A1-01、02.03、A4.02、S-01）。"
            "只返回JSON对象，不要解释："
            "{\"图号\":\"\",\"图名\":\"\",\"置信度\":0.0,\"依据\":\"\"}"
        ),
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

    result = await call_kimi(
        system_prompt="你是施工图汇总Agent，只输出JSON。",
        user_prompt=(
            "请对输入的页级识别结果做统一汇总纠偏，输出每一页最终图号和图名。"
            "可修复轻微OCR误差，但不要凭空新增页。"
            "输入JSON：\n"
            f"{json.dumps(payload, ensure_ascii=False)}\n"
            "只返回JSON数组，不要解释。"
            "数组每项格式："
            "{\"page_index\":0,\"图号\":\"A1-01\",\"图名\":\"平面布置图\",\"置信度\":0.0,\"理由\":\"\"}"
        ),
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

    result = await call_kimi(
        system_prompt="你是施工图匹配校验Agent，只输出JSON。",
        user_prompt=(
            "请将 pages 与 catalog 做一对一匹配：每个 page 至多匹配一个 catalog，每个 catalog 只能使用一次。"
            "允许轻微OCR误差，优先图号，其次图名。"
            "输入JSON：\n"
            f"{json.dumps(payload, ensure_ascii=False)}\n"
            "只返回JSON数组，不要解释。"
            "数组每项格式："
            "{\"page_index\":0,\"catalog_sheet_no\":\"A1-01\",\"catalog_sheet_name\":\"平面布置图\",\"置信度\":0.0,\"理由\":\"\"}"
            "如果无法判断，则对应字段留空字符串。"
        ),
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

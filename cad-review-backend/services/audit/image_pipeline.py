"""尺寸审核图像处理流水线。"""

from __future__ import annotations

import io
import math
from typing import Dict, Tuple


def _resize_to_width(img, max_width: int):
    """将图像宽度限制到给定像素宽度，超过才缩。"""
    from PIL import Image

    if img.width <= max_width:
        return img
    ratio = max_width / img.width
    return img.resize(
        (max_width, max(1, int(img.height * ratio))), Image.Resampling.LANCZOS
    )


_RULER_MARGIN = 32
_TICK_STEP = 10


def _add_ruler_border(
    crop_img,
    x_start: float,
    x_end: float,
    y_start: float,
    y_end: float,
):
    """在裁切图四周扩展白色边距，在边距区域绘制百分比刻度尺。

    原始图纸内容不受任何影响。
    """
    from PIL import Image, ImageDraw, ImageFont

    margin = _RULER_MARGIN
    cw, ch = crop_img.size
    new_w = cw + margin * 2
    new_h = ch + margin * 2

    canvas = Image.new("RGB", (new_w, new_h), (255, 255, 255))
    canvas.paste(crop_img, (margin, margin))

    draw = ImageDraw.Draw(canvas)

    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 14
        )
    except Exception:
        font = ImageFont.load_default()

    label_color = (100, 100, 100)
    tick_color = (140, 140, 140)
    tick_len = 5

    # X-axis ticks (top margin + bottom margin)
    x_range = x_end - x_start
    if x_range > 0:
        pct = math.ceil(x_start / _TICK_STEP) * _TICK_STEP
        while pct <= x_end:
            px = margin + int((pct - x_start) / x_range * cw)
            label = f"{pct:.0f}%"
            # Top ruler
            draw.line([(px, margin - tick_len), (px, margin)], fill=tick_color, width=1)
            draw.text((px + 2, 2), label, fill=label_color, font=font)
            # Bottom ruler
            draw.line([(px, margin + ch), (px, margin + ch + tick_len)], fill=tick_color, width=1)
            draw.text((px + 2, margin + ch + 4), label, fill=label_color, font=font)
            pct += _TICK_STEP

    # Y-axis ticks (left margin + right margin)
    y_range = y_end - y_start
    if y_range > 0:
        pct = math.ceil(y_start / _TICK_STEP) * _TICK_STEP
        while pct <= y_end:
            py = margin + int((pct - y_start) / y_range * ch)
            label = f"{pct:.0f}%"
            # Left ruler
            draw.line([(margin - tick_len, py), (margin, py)], fill=tick_color, width=1)
            draw.text((1, py + 2), label, fill=label_color, font=font)
            # Right ruler
            draw.line([(margin + cw, py), (margin + cw + tick_len, py)], fill=tick_color, width=1)
            draw.text((margin + cw + 4, py + 2), label, fill=label_color, font=font)
            pct += _TICK_STEP

    return canvas


def _to_png_bytes(source) -> bytes:
    """将图像转换为PNG字节流。"""
    buf = io.BytesIO()
    source.save(buf, format="PNG")
    return buf.getvalue()


_QUADRANT_PCT: Dict[str, Tuple[float, float, float, float]] = {
    "top_left":     (0,  0,  60, 60),
    "top_right":    (40, 0,  100, 60),
    "bottom_left":  (0,  40, 60,  100),
    "bottom_right": (40, 40, 100, 100),
}


def pdf_page_to_5images(
    pdf_path: str,
    page_index: int,
    overlap: float = 0.20,
    *,
    full_dpi: float = 200.0,
    detail_dpi: float = 300.0,
    max_width: int = 3840,
) -> Dict[str, bytes]:
    """将PDF单页转换为5张图像。

    - 全图：200 DPI，纯净无叠加
    - 4象限：300 DPI 高清裁切，外扩白色边距绘制百分比刻度尺
    - 刻度画在白色边距区域，不覆盖图纸内容
    - 象限坐标与全图百分比坐标系完全一致
    """
    from PIL import Image
    import fitz

    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(page_index)

        # Full overview at configured DPI
        mat_full = fitz.Matrix(full_dpi / 72, full_dpi / 72)
        pix_full = page.get_pixmap(matrix=mat_full)
        img_full = Image.open(io.BytesIO(pix_full.tobytes("png"))).convert("RGB")
        full = _resize_to_width(img_full, max_width)

        # High-res source at configured DPI for quadrant crops
        mat_high = fitz.Matrix(detail_dpi / 72, detail_dpi / 72)
        pix_high = page.get_pixmap(matrix=mat_high)
        img_src = Image.open(io.BytesIO(pix_high.tobytes("png"))).convert("RGB")

        width, height = img_src.size
        cx = width // 2
        cy = height // 2
        ox = int(width * overlap / 2.0)
        oy = int(height * overlap / 2.0)

        pixel_boxes = {
            "top_left":     (0,      0,      cx + ox, cy + oy),
            "top_right":    (cx - ox, 0,      width,   cy + oy),
            "bottom_left":  (0,      cy - oy, cx + ox, height),
            "bottom_right": (cx - ox, cy - oy, width,   height),
        }

        qbytes: Dict[str, bytes] = {}
        for name, box in pixel_boxes.items():
            crop = _resize_to_width(img_src.crop(box), max_width)
            x_start, y_start, x_end, y_end = _QUADRANT_PCT[name]
            bordered = _add_ruler_border(crop, x_start, x_end, y_start, y_end)
            qbytes[name] = _to_png_bytes(bordered)

        return {
            "full": _to_png_bytes(full),
            "top_left": qbytes["top_left"],
            "top_right": qbytes["top_right"],
            "bottom_left": qbytes["bottom_left"],
            "bottom_right": qbytes["bottom_right"],
        }
    finally:
        doc.close()

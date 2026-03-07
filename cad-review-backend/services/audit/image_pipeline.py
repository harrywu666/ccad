"""尺寸审核图像处理流水线。"""

from __future__ import annotations

import io
from typing import Dict


# 功能说明：将图像缩放到4K分辨率（宽度3840像素）
def _resize_to_4k(img):
    from PIL import Image

    target_w = 3840
    if img.width <= target_w:
        return img
    ratio = target_w / img.width
    return img.resize(
        (target_w, max(1, int(img.height * ratio))), Image.Resampling.LANCZOS
    )


# 功能说明：在图像上绘制网格线和标签
def _draw_grid(img):
    from PIL import ImageDraw, ImageFont

    grid_cols = 24
    grid_rows = 17
    labels = "ABCDEFGHIJKLMNOPQRSTUVWX"
    draw = ImageDraw.Draw(img)
    width, height = img.size
    col_w = width / grid_cols
    row_h = height / grid_rows
    color = (220, 220, 220)

    for i in range(1, grid_cols):
        x = int(i * col_w)
        draw.line([(x, 0), (x, height)], fill=color, width=1)
    for j in range(1, grid_rows):
        y = int(j * row_h)
        draw.line([(0, y), (width, y)], fill=color, width=1)

    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 18
        )
    except Exception:
        font = ImageFont.load_default()

    for i in range(grid_cols):
        text = labels[i]
        x = int((i + 0.5) * col_w) - 6
        draw.text((x, 4), text, fill=(120, 120, 120), font=font)
        draw.text((x, height - 24), text, fill=(120, 120, 120), font=font)
    for j in range(grid_rows):
        text = str(j + 1)
        y = int((j + 0.5) * row_h) - 8
        draw.text((4, y), text, fill=(120, 120, 120), font=font)
        draw.text((width - 20, y), text, fill=(120, 120, 120), font=font)
    return img


# 功能说明：将图像转换为PNG字节流
def _to_png_bytes(source) -> bytes:
    buf = io.BytesIO()
    source.save(buf, format="PNG")
    return buf.getvalue()


# 功能说明：将PDF单页转换为5张图像（1张全景+4张象限截图）
def pdf_page_to_5images(
    pdf_path: str, page_index: int, overlap: float = 0.20
) -> Dict[str, bytes]:
    from PIL import Image
    import fitz

    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(page_index)

        mat_low = fitz.Matrix(150 / 72, 150 / 72)
        pix_low = page.get_pixmap(matrix=mat_low)
        img_full = Image.open(io.BytesIO(pix_low.tobytes("png"))).convert("RGB")
        full = _draw_grid(_resize_to_4k(img_full))

        mat_high = fitz.Matrix(300 / 72, 300 / 72)
        pix_high = page.get_pixmap(matrix=mat_high)
        img_src = Image.open(io.BytesIO(pix_high.tobytes("png"))).convert("RGB")

        width, height = img_src.size
        cx = width // 2
        cy = height // 2
        ox = int(width * overlap / 2.0)
        oy = int(height * overlap / 2.0)
        boxes = {
            "top_left": (0, 0, cx + ox, cy + oy),
            "top_right": (cx - ox, 0, width, cy + oy),
            "bottom_left": (0, cy - oy, cx + ox, height),
            "bottom_right": (cx - ox, cy - oy, width, height),
        }

        qbytes: Dict[str, bytes] = {}
        for name, box in boxes.items():
            crop = _resize_to_4k(img_src.crop(box))
            qbytes[name] = _to_png_bytes(crop)

        return {
            "full": _to_png_bytes(full),
            "top_left": qbytes["top_left"],
            "top_right": qbytes["top_right"],
            "bottom_left": qbytes["bottom_left"],
            "bottom_right": qbytes["bottom_right"],
        }
    finally:
        doc.close()

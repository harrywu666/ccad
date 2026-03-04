"""
PDF处理服务模块
提供PDF转PNG、裁剪、缩略图生成功能
"""

import io
from typing import Tuple
from PIL import Image
import fitz


def pdf_to_pngs_stream(pdf_path: str, output_dir: str, callback=None):
    """
    PDF流式转换为PNG
    
    Args:
        pdf_path: PDF文件路径
        output_dir: 输出目录
        callback: 每页处理完成后的回调函数
    """
    doc = fitz.open(pdf_path)
    total = len(doc)
    
    for page_index in range(total):
        page = doc.load_page(page_index)
        pix = page.get_pixmap(dpi=300)
        png_data = pix.tobytes("png")
        
        output_path = f"{output_dir}/page_{page_index + 1}.png"
        with open(output_path, "wb") as f:
            f.write(png_data)
        
        if callback:
            callback({
                "page_index": page_index + 1,
                "total": total,
                "png_path": output_path
            })
    
    doc.close()
    return total


def crop_region(png_bytes: bytes, x: int, y: int, width: int, height: int) -> bytes:
    """
    裁剪PNG图片指定区域
    
    Args:
        png_bytes: PNG图片bytes
        x: 左上角X坐标
        y: 左上角Y坐标
        width: 裁剪宽度
        height: 裁剪高度
    
    Returns:
        裁剪后的PNG bytes
    """
    img = Image.open(io.BytesIO(png_bytes))
    cropped = img.crop((x, y, x + width, y + height))
    
    buffer = io.BytesIO()
    cropped.save(buffer, format="PNG")
    return buffer.getvalue()


def create_thumbnail(png_bytes: bytes, max_width: int = 800) -> bytes:
    """
    生成PNG缩略图
    
    Args:
        png_bytes: PNG图片bytes
        max_width: 最大宽度
    
    Returns:
        缩略图bytes
    """
    img = Image.open(io.BytesIO(png_bytes))
    
    if img.width > max_width:
        ratio = max_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
    
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def get_page_count(pdf_path: str) -> int:
    """
    获取PDF页数
    
    Args:
        pdf_path: PDF文件路径
    
    Returns:
        页数
    """
    doc = fitz.open(pdf_path)
    count = len(doc)
    doc.close()
    return count

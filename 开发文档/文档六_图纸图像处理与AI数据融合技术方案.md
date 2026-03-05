# 文档六：图纸图像处理与AI数据融合技术方案
## 室内装饰施工图 AI 自动审核系统

**版本：V1.0 | 日期：2026年2月**
**定位：核心技术难点详解，直接指导代码编写**

---

## 一、问题背景与设计目标

### 1.1 核心矛盾

室内装饰施工图标准图幅为 **A1（841mm × 594mm）**，以300 DPI导出后：

```
宽：841 ÷ 25.4 × 300 = 9922 px
高：594 ÷ 25.4 × 300 = 7016 px
文件大小：约 70MP，远超 Kimi 支持的最大分辨率
```

Kimi K2.5 支持的最大输入分辨率为 **4K（约3840 × 2160）**，直接发送会被强制压缩至约38%。压缩后每毫米仅约4.6px，密集标注区域的数字完全无法辨认。

### 1.2 两个不能妥协的需求

| 需求 | 原因 |
|------|------|
| Kimi必须看到完整图纸 | 施工图的语义理解依赖全局空间关系，裁图会丢失上下文 |
| 标注数字必须清晰 | 尺寸数值是审核的核心依据，模糊了就失去意义 |

### 1.3 设计目标

用**5张图 + 结构化数据 + 坐标体系**三者有机融合，让Kimi同时具备：
- 完整的空间语义理解能力（全图）
- 清晰的局部细节识别能力（高清象限）
- 精确的数值数据（CAD提取的JSON，通过坐标注入Prompt）

---

## 二、整体方案概述

### 2.1 Kimi图像识别流程

Kimi K2.5的图像识别遵循以下流程：

```
1. 图像输入     原生视觉接口，支持4K，base64编码
      ↓
2. 特征提取     MoonViT-3D编码器，对完整图像提取空间特征
               此阶段已完成对图纸的空间结构感知
      ↓
3. 跨模态对齐   MLP投影层，将视觉特征映射至语言模型嵌入空间
      ↓
4. 语义理解  ←←←  【数据注入点】
               语言模型同时接收：
               ① 来自步骤3的视觉特征（图纸空间理解）
               ② 来自JSON的精确数值+坐标（Prompt文字形式）
               两者在语言空间融合推理
      ↓
5. 推理输出     基于完整图纸理解+精确数据，输出审核结论
```

**关键洞察：** 数据注入发生在第4步语义理解阶段，此时视觉系统已完成整图感知。注入的是坐标定位文字，不是在图像上做任何叠加。图像永远保持干净，数值永远精确。

### 2.2 五图方案

```
图1：全图（150 DPI → 缩放至3840px宽）
     作用：建立整体空间认知
     Kimi通过这张图理解：哪里是卧室/客厅/走道/厨房

图2：左上象限高清（300 DPI裁切 → 缩放至3840px宽）
图3：右上象限高清（300 DPI裁切 → 缩放至3840px宽）
图4：左下象限高清（300 DPI裁切 → 缩放至3840px宽）
图5：右下象限高清（300 DPI裁切 → 缩放至3840px宽）
     作用：提供标注文字可读的高清细节
     等效分辨率：每mm约9.2px（全图4K的2倍）
```

### 2.3 重叠区域设计

四个象限之间必须有重叠，避免硬切导致边界处的墙体、空间、标注被割断：

```
重叠比例：20%（横向和纵向均为20%）

每个象限实际覆盖原图的60%宽 × 60%高
相邻象限之间有20%的内容重叠
四图中心有一个20%×20%的四图共有区域

具体像素：
  原图：9922 × 7016
  横向重叠宽度：9922 × 20% = 1984px（约168mm图纸）
  纵向重叠高度：7016 × 20% = 1403px（约119mm图纸）
  每个象限尺寸：5953 × 4210px
  缩放后：3840 × 2720px（在4K限制内）
```

重叠区域图示：

```
原图坐标系（百分比）：

X轴：0%                    50%                   100%
      │←────── 图2左上(0-60%) ──────→│
                       │←────── 图3右上(40-100%) ──────→│
      ↑重叠区X: 40%-60%↑

Y轴：0%
      │←── 图2左上(0-60%) ──→│  │←── 图3右上(0-60%) ──→│
      50%
      │←── 图4左下(40-100%) →│  │←── 图5右下(40-100%) →│
      100%
      ↑重叠区Y: 40%-60%↑

各象限覆盖范围（含重叠）：
  图2左上：X∈[0%,  60%]，Y∈[0%,  60%]
  图3右上：X∈[40%, 100%]，Y∈[0%,  60%]
  图4左下：X∈[0%,  60%]，Y∈[40%, 100%]
  图5右下：X∈[40%, 100%]，Y∈[40%, 100%]

重叠带实际图纸尺寸：
  横向重叠（X方向）：841mm × 20% = 168mm
  纵向重叠（Y方向）：594mm × 20% = 119mm
  168mm > 最厚砌块墙（240mm的一半），足以保证没有构件被割断
```

---

## 三、坐标体系设计

### 3.1 三套坐标系及其关系

本方案使用三套坐标系，需要明确区分：

```
① CAD模型空间坐标（单位：mm或CAD单位）
  来源：AutoLISP插件提取，存储在JSON中
  示例：(3200.0, 4500.0)
  特点：绝对精确，原点因图纸而异

② 全图百分比坐标（单位：%）
  来源：由①换算得到
  示例：{"x": 38.2, "y": 64.5}
  特点：与图幅无关，左上角为(0,0)，右下角为(100,100)
  注意：Y轴需翻转（CAD向上为正，PNG向下为正）

③ 象限内局部百分比坐标（单位：%）
  来源：由②换算得到
  示例：{"local_x_pct": 47.0, "local_y_pct": 41.2}
  特点：相对于各象限图的左上角，同一数据点在不同象限有不同值
```

### 3.2 坐标换算公式

**① → ②（CAD坐标 → 全图百分比）：**

```python
def cad_to_global_pct(cad_x, cad_y, model_range):
    """
    将CAD模型空间坐标换算为全图百分比坐标
    
    model_range：该布局视口对应的模型空间范围
      {"min": [x_min, y_min], "max": [x_max, y_max]}
    
    注意：Y轴翻转，因为CAD向上为正，PNG向下为正
    """
    x_min, y_min = model_range["min"]
    x_max, y_max = model_range["max"]
    
    pct_x = (cad_x - x_min) / (x_max - x_min) * 100
    # Y轴翻转
    pct_y = (1 - (cad_y - y_min) / (y_max - y_min)) * 100
    
    # 限制在0-100范围内（视口边缘的标注可能略微超出）
    pct_x = max(0.0, min(100.0, pct_x))
    pct_y = max(0.0, min(100.0, pct_y))
    
    return round(pct_x, 1), round(pct_y, 1)
```

**② → ③（全图百分比 → 象限内局部百分比）：**

```python
def global_pct_to_quadrant_pct(global_x, global_y, overlap=0.20):
    """
    将全图百分比坐标换算为各象限的局部百分比坐标
    同时判断该点属于哪些象限（重叠区域的点属于多个象限）
    
    返回：
    {
        "图2左上": {"local_x_pct": 47.0, "local_y_pct": 41.2},
        "图4左下": {"local_x_pct": 47.0, "local_y_pct": 3.5}
    }
    空字典表示该点不在任何已定义象限内（理论上不会发生）
    """
    ext = (overlap / 2) * 100   # 每侧延伸的百分比，默认10%
    half = 50.0

    # 各象限在全图中的覆盖范围
    quadrant_ranges = {
        "图2左上": {
            "x_start": 0,          "x_end": half + ext,   # 0% ~ 60%
            "y_start": 0,          "y_end": half + ext,   # 0% ~ 60%
        },
        "图3右上": {
            "x_start": half - ext, "x_end": 100,          # 40% ~ 100%
            "y_start": 0,          "y_end": half + ext,   # 0% ~ 60%
        },
        "图4左下": {
            "x_start": 0,          "x_end": half + ext,   # 0% ~ 60%
            "y_start": half - ext, "y_end": 100,          # 40% ~ 100%
        },
        "图5右下": {
            "x_start": half - ext, "x_end": 100,          # 40% ~ 100%
            "y_start": half - ext, "y_end": 100,          # 40% ~ 100%
        },
    }

    result = {}
    for quad_name, r in quadrant_ranges.items():
        if r["x_start"] <= global_x <= r["x_end"] and \
           r["y_start"] <= global_y <= r["y_end"]:
            # 换算为象限内的局部百分比
            quad_width  = r["x_end"] - r["x_start"]
            quad_height = r["y_end"] - r["y_start"]
            local_x = (global_x - r["x_start"]) / quad_width  * 100
            local_y = (global_y - r["y_start"]) / quad_height * 100
            result[quad_name] = {
                "local_x_pct": round(local_x, 1),
                "local_y_pct": round(local_y, 1),
            }

    return result
```

### 3.3 棋盘格坐标

在全图百分比坐标基础上，叠加人类可读的棋盘格标签：

```python
def global_pct_to_grid(global_x, global_y, cols=24, rows=17):
    """
    将全图百分比坐标换算为棋盘格坐标（如 "F11"）
    
    棋盘格规格：24列（A-X）× 17行（1-17）
    针对A1图幅在4K分辨率下的最优设计：
      每格约 160 × 160px（4K图）
      对应图纸约 35mm × 35mm
      对应实际空间约 1750mm × 1750mm（1:50比例）
    """
    col_labels = "ABCDEFGHIJKLMNOPQRSTUVWX"   # 24列
    
    col_idx = int(global_x / 100 * cols)
    row_idx = int(global_y / 100 * rows)
    
    # 边界保护
    col_idx = max(0, min(cols - 1, col_idx))
    row_idx = max(0, min(rows - 1, row_idx))
    
    return f"{col_labels[col_idx]}{row_idx + 1}"   # 如 "F11"
```

---

## 四、图像处理模块

### 4.1 完整实现代码

文件路径：`services/image_service.py`

```python
"""
图像处理服务
负责将PDF页面转换为供Kimi分析的5张图（1全图 + 4象限重叠图）
并叠加棋盘格辅助坐标
"""
import io
import math
from PIL import Image, ImageDraw, ImageFont
import fitz   # PyMuPDF


# ── 配置常量 ──────────────────────────────────────────────────────────────────
GRID_COLS    = 24          # 棋盘格列数
GRID_ROWS    = 17          # 棋盘格行数
GRID_OVERLAP = 0.20        # 象限重叠比例（20%）
TARGET_4K_W  = 3840        # Kimi支持的最大宽度
GRID_LINE_COLOR  = (80, 80, 80, 55)     # 格线颜色（RGBA，半透明）
GRID_LABEL_COLOR = (60, 60, 60, 160)    # 标签颜色（RGBA）
GRID_LABEL_SIZE  = 22      # 标签字体大小（px）


def _draw_grid(img: Image.Image) -> Image.Image:
    """
    在图像上叠加半透明棋盘格
    格线极细且半透明，不干扰图纸内容识别
    """
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = img.size
    col_w = w / GRID_COLS
    row_h = h / GRID_ROWS
    col_labels = "ABCDEFGHIJKLMNOPQRSTUVWX"

    # 绘制格线
    for i in range(1, GRID_COLS):
        x = int(i * col_w)
        draw.line([(x, 0), (x, h)], fill=GRID_LINE_COLOR, width=1)
    for j in range(1, GRID_ROWS):
        y = int(j * row_h)
        draw.line([(0, y), (w, y)], fill=GRID_LINE_COLOR, width=1)

    # 绘制列标签（A-X，顶部和底部各一次）
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                                   GRID_LABEL_SIZE)
    except Exception:
        font = ImageFont.load_default()

    for i in range(GRID_COLS):
        label = col_labels[i]
        x = int((i + 0.5) * col_w) - GRID_LABEL_SIZE // 2
        draw.text((x, 4),      label, font=font, fill=GRID_LABEL_COLOR)
        draw.text((x, h - 26), label, font=font, fill=GRID_LABEL_COLOR)

    # 绘制行标签（1-17，左侧和右侧各一次）
    for j in range(GRID_ROWS):
        label = str(j + 1)
        y = int((j + 0.5) * row_h) - GRID_LABEL_SIZE // 2
        draw.text((4,      y), label, font=font, fill=GRID_LABEL_COLOR)
        draw.text((w - 22, y), label, font=font, fill=GRID_LABEL_COLOR)

    # 合并图层
    base = img.convert("RGBA")
    combined = Image.alpha_composite(base, overlay)
    return combined.convert("RGB")


def _img_to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _resize_to_4k(img: Image.Image) -> Image.Image:
    """按长边缩放，不超过4K宽度，保持宽高比"""
    if img.width <= TARGET_4K_W:
        return img
    img_copy = img.copy()
    img_copy.thumbnail((TARGET_4K_W, TARGET_4K_W), Image.LANCZOS)
    return img_copy


def pdf_page_to_5images(page: fitz.Page, overlap: float = GRID_OVERLAP) -> dict:
    """
    将PDF单页转换为5张图：
      - full：全图（加棋盘格，4K内）
      - top_left / top_right / bottom_left / bottom_right：四个高清象限（各含20%重叠）

    参数：
      page：PyMuPDF的页面对象
      overlap：象限重叠比例，默认0.20（20%）

    返回：
    {
        "full":         bytes,   # 图1：全图（带棋盘格）
        "top_left":     bytes,   # 图2：左上象限
        "top_right":    bytes,   # 图3：右上象限
        "bottom_left":  bytes,   # 图4：左下象限
        "bottom_right": bytes,   # 图5：右下象限
        "full_size":    (w, h),  # 全图缩放后的实际像素尺寸（用于坐标换算）
        "src_size":     (w, h),  # 高清源图的像素尺寸（300DPI）
    }
    """

    # ── 图1：全图（150 DPI导出 → 缩放至4K → 叠加棋盘格）────────────────────
    mat_low = fitz.Matrix(150 / 72, 150 / 72)
    pix_low = page.get_pixmap(matrix=mat_low)
    img_full_raw = Image.open(io.BytesIO(pix_low.tobytes("png")))
    img_full_resized = _resize_to_4k(img_full_raw)
    img_full_grid = _draw_grid(img_full_resized)

    # ── 图2-5：高清源图（300 DPI导出）───────────────────────────────────────
    mat_high = fitz.Matrix(300 / 72, 300 / 72)
    pix_high = page.get_pixmap(matrix=mat_high)
    img_src = Image.open(io.BytesIO(pix_high.tobytes("png")))
    W, H = img_src.size   # 约 9922 × 7016

    # 计算切割点（中心 + 各方向延伸 overlap/2）
    cx  = W // 2
    cy  = H // 2
    ox  = int(W * overlap / 2)   # 横向重叠半径
    oy  = int(H * overlap / 2)   # 纵向重叠半径

    # 四块裁切坐标 (left, top, right, bottom)
    crop_boxes = {
        "top_left":     (0,       0,       cx + ox, cy + oy),
        "top_right":    (cx - ox, 0,       W,       cy + oy),
        "bottom_left":  (0,       cy - oy, cx + ox, H      ),
        "bottom_right": (cx - ox, cy - oy, W,       H      ),
    }

    quadrant_images = {}
    for name, box in crop_boxes.items():
        crop = img_src.crop(box)
        crop_resized = _resize_to_4k(crop)
        buf = io.BytesIO()
        crop_resized.save(buf, format="PNG")
        quadrant_images[name] = buf.getvalue()

    return {
        "full":          _img_to_bytes(img_full_grid),
        "top_left":      quadrant_images["top_left"],
        "top_right":     quadrant_images["top_right"],
        "bottom_left":   quadrant_images["bottom_left"],
        "bottom_right":  quadrant_images["bottom_right"],
        "full_size":     img_full_resized.size,    # (w, h) 全图缩放后尺寸
        "src_size":      (W, H),                   # (w, h) 高清源图尺寸
    }
```

---

## 五、坐标计算模块

### 5.1 完整实现代码

文件路径：`services/coordinate_service.py`

```python
"""
坐标计算服务
负责将CAD坐标系统转换为图像坐标系统，并分配象限归属
"""

GRID_COLS    = 24
GRID_ROWS    = 17
GRID_OVERLAP = 0.20
COL_LABELS   = "ABCDEFGHIJKLMNOPQRSTUVWX"


def cad_to_global_pct(cad_x: float, cad_y: float, model_range: dict) -> tuple:
    """
    CAD模型空间坐标 → 全图百分比坐标

    model_range格式：{"min": [x_min, y_min], "max": [x_max, y_max]}
    
    Y轴翻转原因：
      CAD坐标系：Y轴向上为正
      PNG坐标系：Y轴向下为正（左上角为原点）

    返回：(pct_x, pct_y) 均为0.0~100.0的浮点数
    """
    x_min, y_min = model_range["min"]
    x_max, y_max = model_range["max"]

    if x_max == x_min or y_max == y_min:
        return 50.0, 50.0   # 防止除以零

    pct_x = (cad_x - x_min) / (x_max - x_min) * 100
    pct_y = (1.0 - (cad_y - y_min) / (y_max - y_min)) * 100

    pct_x = max(0.0, min(100.0, round(pct_x, 1)))
    pct_y = max(0.0, min(100.0, round(pct_y, 1)))
    return pct_x, pct_y


def global_pct_to_grid(pct_x: float, pct_y: float) -> str:
    """
    全图百分比坐标 → 棋盘格坐标（如 "F11"）

    棋盘格：24列（A-X）× 17行（1-17）
    """
    col_idx = int(pct_x / 100 * GRID_COLS)
    row_idx = int(pct_y / 100 * GRID_ROWS)
    col_idx = max(0, min(GRID_COLS - 1, col_idx))
    row_idx = max(0, min(GRID_ROWS - 1, row_idx))
    return f"{COL_LABELS[col_idx]}{row_idx + 1}"


def global_pct_to_quadrants(pct_x: float, pct_y: float,
                              overlap: float = GRID_OVERLAP) -> dict:
    """
    全图百分比坐标 → 各象限内局部百分比坐标

    overlap=0.20 时各象限覆盖范围：
      图2左上：X∈[0%,  60%]，Y∈[0%,  60%]
      图3右上：X∈[40%, 100%]，Y∈[0%,  60%]
      图4左下：X∈[0%,  60%]，Y∈[40%, 100%]
      图5右下：X∈[40%, 100%]，Y∈[40%, 100%]

    落在重叠区域的点会同时出现在多个象限中

    返回示例：
    {
        "图2左上": {"local_x_pct": 85.3, "local_y_pct": 78.8},
        "图4左下": {"local_x_pct": 85.3, "local_y_pct": 12.2}
    }
    """
    ext  = (overlap / 2) * 100   # 每侧延伸量（默认10%）
    half = 50.0

    quadrant_ranges = {
        "图2左上": {"x": (0,          half + ext), "y": (0,          half + ext)},
        "图3右上": {"x": (half - ext, 100.0      ), "y": (0,          half + ext)},
        "图4左下": {"x": (0,          half + ext), "y": (half - ext, 100.0      )},
        "图5右下": {"x": (half - ext, 100.0      ), "y": (half - ext, 100.0      )},
    }

    result = {}
    for quad_name, r in quadrant_ranges.items():
        x0, x1 = r["x"]
        y0, y1 = r["y"]
        if x0 <= pct_x <= x1 and y0 <= pct_y <= y1:
            local_x = (pct_x - x0) / (x1 - x0) * 100
            local_y = (pct_y - y0) / (y1 - y0) * 100
            result[quad_name] = {
                "local_x_pct": round(local_x, 1),
                "local_y_pct": round(local_y, 1),
            }
    return result


def enrich_json_with_coordinates(layout_json: dict) -> dict:
    """
    将CAD插件输出的JSON数据，为每个数据点补充完整坐标信息

    输入：原始layout JSON（来自AutoLISP插件）
    输出：补充了 global_pct、grid、in_quadrants 字段的增强JSON

    处理的数据类型：
      - dimensions（尺寸标注）：用 text_position 字段换算
      - indexes（索引符号）：用 position 字段换算
      - materials（材料标注）：用 position 字段换算
    """
    model_range = layout_json.get("model_range")
    if not model_range:
        raise ValueError("JSON缺少model_range字段，无法进行坐标换算")

    def _enrich(item: dict, pos_key: str) -> dict:
        pos = item.get(pos_key)
        if not pos or len(pos) < 2:
            return item

        cad_x, cad_y = pos[0], pos[1]
        pct_x, pct_y = cad_to_global_pct(cad_x, cad_y, model_range)

        item["global_pct"]   = {"x": pct_x, "y": pct_y}
        item["grid"]         = global_pct_to_grid(pct_x, pct_y)
        item["in_quadrants"] = global_pct_to_quadrants(pct_x, pct_y)
        return item

    enriched = layout_json.copy()

    # 尺寸标注：用文字位置（text_position）换算，更接近标注视觉位置
    enriched["dimensions"] = [
        _enrich(d, "text_position") for d in layout_json.get("dimensions", [])
    ]

    # 索引符号：用插入点坐标换算
    enriched["indexes"] = [
        _enrich(i, "position") for i in layout_json.get("indexes", [])
    ]

    # 材料标注：用引线箭头坐标换算
    enriched["materials"] = [
        _enrich(m, "position") for m in layout_json.get("materials", [])
    ]

    return enriched
```

---

## 六、Prompt构造模块

### 6.1 完整实现代码

文件路径：`services/prompt_service.py`

```python
"""
Prompt构造服务
将增强后的JSON数据组织成结构化Prompt，按象限分组，供Kimi分析
"""
import json
from collections import defaultdict


QUADRANT_NAMES = ["图2左上", "图3右上", "图4左下", "图5右下"]

# 各象限在全图中的覆盖范围描述（用于Prompt）
QUADRANT_COVERAGE = {
    "图2左上": "覆盖全图左60%宽、上60%高（X:0-60%, Y:0-60%）",
    "图3右上": "覆盖全图右60%宽、上60%高（X:40-100%, Y:0-60%）",
    "图4左下": "覆盖全图左60%宽、下60%高（X:0-60%, Y:40-100%）",
    "图5右下": "覆盖全图右60%宽、下60%高（X:40-100%, Y:40-100%）",
}

# 象限名称与图片编号的对应
QUADRANT_IMG_NO = {
    "图2左上": "图2",
    "图3右上": "图3",
    "图4左下": "图4",
    "图5右下": "图5",
}


def _group_by_quadrant(data_list: list, data_type: str) -> dict:
    """
    将数据列表按象限分组

    data_type: "dimension" | "index" | "material"
    返回：{"图2左上": [...], "图3右上": [...], ...}
    """
    groups = defaultdict(list)
    for item in data_list:
        in_quadrants = item.get("in_quadrants", {})
        if not in_quadrants:
            # 坐标换算失败的数据，归入「未定位」
            groups["未定位"].append(item)
            continue
        for quad_name, local_coords in in_quadrants.items():
            groups[quad_name].append({
                **item,
                "_local_coords": local_coords,   # 该象限内的局部坐标
            })
    return dict(groups)


def _format_dimension(d: dict) -> str:
    local = d.get("_local_coords", {})
    grid  = d.get("grid", "?")
    value = d.get("value", "?")
    layer = d.get("layer", "")
    lx    = local.get("local_x_pct", "?")
    ly    = local.get("local_y_pct", "?")

    note = ""
    if len(d.get("in_quadrants", {})) > 1:
        note = "（重叠区，多象限可见）"

    return (f"  · 尺寸 {value}mm"
            f"  全图位置:{grid}  "
            f"象限内位置:左{lx}%/上{ly}%  "
            f"图层:{layer}{note}")


def _format_index(idx: dict) -> str:
    local    = idx.get("_local_coords", {})
    grid     = idx.get("grid", "?")
    no       = idx.get("index_no", "?")
    target   = idx.get("target_sheet", "?")
    lx       = local.get("local_x_pct", "?")
    ly       = local.get("local_y_pct", "?")
    return (f"  · 索引{no} → {target}"
            f"  全图位置:{grid}  "
            f"象限内位置:左{lx}%/上{ly}%")


def _format_material(m: dict) -> str:
    local  = m.get("_local_coords", {})
    grid   = m.get("grid", "?")
    code   = m.get("code", "?")
    name   = m.get("name", "")
    lx     = local.get("local_x_pct", "?")
    ly     = local.get("local_y_pct", "?")
    return (f"  · 材料 {code} {name}"
            f"  全图位置:{grid}  "
            f"象限内位置:左{lx}%/上{ly}%")


def build_audit_prompt(
    enriched_json: dict,
    audit_task: str,
    sheet_no: str = "",
    sheet_name: str = "",
) -> str:
    """
    构造完整的审核Prompt

    参数：
      enriched_json：经过 enrich_json_with_coordinates() 处理后的JSON
      audit_task：本次审核任务描述（由调用方传入，针对不同审核步骤）
      sheet_no：图号（如 A1-01）
      sheet_name：图名（如 平面布置图）

    返回：完整的Prompt字符串，直接传入Kimi API的user_prompt
    """
    dimensions = enriched_json.get("dimensions", [])
    indexes    = enriched_json.get("indexes",    [])
    materials  = enriched_json.get("materials",  [])

    # 按象限分组
    dim_groups = _group_by_quadrant(dimensions, "dimension")
    idx_groups = _group_by_quadrant(indexes,    "index"    )
    mat_groups = _group_by_quadrant(materials,  "material" )

    # 统计各象限数据量
    all_quads = set(list(dim_groups.keys()) +
                    list(idx_groups.keys()) +
                    list(mat_groups.keys()))

    lines = []

    # ── 图片说明 ──────────────────────────────────────────────────────────────
    lines.append("═" * 60)
    lines.append(f"图纸：{sheet_no} {sheet_name}")
    lines.append("═" * 60)
    lines.append("")
    lines.append("【图片说明】")
    lines.append("图1：完整施工图（全局空间理解用），叠加了 A-X列（24列）× 1-17行 坐标网格。")
    lines.append("图2-5：同一张图切成的四个高清象限（细节识别用），相邻象限之间有20%内容重叠：")
    for qname, coverage in QUADRANT_COVERAGE.items():
        img_no = QUADRANT_IMG_NO[qname]
        lines.append(f"  {img_no}（{qname}）：{coverage}")
    lines.append("")
    lines.append("坐标说明：")
    lines.append("  全图位置：棋盘格坐标，如「F11」表示F列第11行")
    lines.append("  象限内位置：在该象限图中的百分比位置，左上角为原点(0%,0%)")
    lines.append("  重叠区：标注「重叠区，多象限可见」的数据点同时出现在多张象限图中")
    lines.append("")

    # ── 按象限组织数据 ─────────────────────────────────────────────────────────
    lines.append("【精确数据（来自DWG，数值100%准确）】")
    lines.append("以下数据已按象限分组，请在对应的高清象限图中定位验证：")
    lines.append("")

    for qname in QUADRANT_NAMES:
        img_no   = QUADRANT_IMG_NO[qname]
        q_dims   = dim_groups.get(qname, [])
        q_idxs   = idx_groups.get(qname, [])
        q_mats   = mat_groups.get(qname, [])

        if not q_dims and not q_idxs and not q_mats:
            continue

        lines.append(f"── {img_no}（{qname}）中的数据 ──")

        if q_dims:
            lines.append(f"  [尺寸标注 {len(q_dims)}个]")
            for d in q_dims:
                lines.append(_format_dimension(d))

        if q_idxs:
            lines.append(f"  [索引符号 {len(q_idxs)}个]")
            for i in q_idxs:
                lines.append(_format_index(i))

        if q_mats:
            lines.append(f"  [材料标注 {len(q_mats)}个]")
            for m in q_mats:
                lines.append(_format_material(m))

        lines.append("")

    # 未定位的数据
    unlocated = (dim_groups.get("未定位", []) +
                 idx_groups.get("未定位", []) +
                 mat_groups.get("未定位", []))
    if unlocated:
        lines.append("── 坐标定位失败的数据（请凭视觉判断）──")
        for item in unlocated:
            lines.append(f"  · {item}")
        lines.append("")

    # 材料表
    material_table = enriched_json.get("material_table", [])
    if material_table:
        lines.append("── 材料总表 ──")
        for mt in material_table:
            lines.append(f"  {mt.get('code','')}：{mt.get('name','')}")
        lines.append("")

    # ── 审核任务 ──────────────────────────────────────────────────────────────
    lines.append("═" * 60)
    lines.append("【审核任务】")
    lines.append(audit_task)
    lines.append("")
    lines.append("审核步骤建议：")
    lines.append("  1. 先通过图1建立对整张图纸的空间理解（房间布局、功能分区）")
    lines.append("  2. 根据数据的「全图位置」棋盘格坐标，在图1上确认大致区域")
    lines.append("  3. 在对应的高清象限图（图2-5）中，")
    lines.append("     用「象限内位置」百分比精确定位，确认标注语义")
    lines.append("  4. 结合精确数值与视觉理解，给出审核结论")
    lines.append("")
    lines.append("返回严格的JSON格式，不要任何解释或markdown代码块。")

    return "\n".join(lines)
```

---

## 七、审核任务Prompt模板

### 7.1 尺寸核对任务

```python
DIMENSION_AUDIT_TASK = """
对这张图纸（{sheet_no} {sheet_name}）进行尺寸语义分析：

对每个尺寸标注，请判断：
  1. 这个尺寸标注的是什么构件（哪面墙/哪个开口/哪个空间的什么方向）
  2. 标注的具体位置描述（如：主卧东侧墙体净宽 / B-C轴1-2轴范围内走道宽度）
  3. 是总尺寸还是分段尺寸

返回JSON格式：
[
  {{
    "id": "dim_001",
    "semantic": "主卧东侧墙体净宽",
    "location_desc": "B轴至C轴，主卧室内净距",
    "dim_type": "分段",
    "value": 2400,
    "grid": "F11",
    "confidence": 0.95
  }}
]
"""
```

### 7.2 索引核对任务

```python
INDEX_AUDIT_TASK = """
对这张图纸（{sheet_no} {sheet_name}）进行索引符号核查：

请确认：
  1. 每个索引符号的空间位置是否合理（索引的位置与指向的内容是否匹配）
  2. 索引符号周围的空间语境（这里索引大样是否合理）

返回JSON格式：
[
  {{
    "id": "idx_001",
    "index_no": "①",
    "target_sheet": "A2-01",
    "location_desc": "主卧东侧墙体中部，指向该墙体的立面详图",
    "spatial_reasonable": true,
    "grid": "H6",
    "confidence": 0.92
  }}
]
"""
```

### 7.3 材料核对任务

```python
MATERIAL_AUDIT_TASK = """
对这张图纸（{sheet_no} {sheet_name}）进行材料标注核查：

请确认：
  1. 每个材料标注对应的构件（地面/墙面/顶面/家具/哪个具体位置）
  2. 材料编号与材料总表的对应是否合理

返回JSON格式：
[
  {{
    "id": "mat_001",
    "code": "F1",
    "name": "餐桌 DINING TABLE",
    "target_component": "餐厅区域主餐桌",
    "location_desc": "餐厅中央，C-D轴/5-6轴范围",
    "in_material_table": true,
    "grid": "D5",
    "confidence": 0.98
  }}
]
"""
```

---

## 八、完整调用流程

### 8.1 单张图纸的完整处理流程

```python
# services/audit_service.py 中调用示例

from services.image_service      import pdf_page_to_5images
from services.coordinate_service import enrich_json_with_coordinates
from services.prompt_service     import build_audit_prompt, DIMENSION_AUDIT_TASK
from services.kimi_service       import call_kimi

import fitz

async def analyze_single_drawing(
    pdf_path: str,
    page_index: int,
    layout_json: dict,      # 来自CAD插件的原始JSON（单个布局）
    audit_type: str,        # "dimension" | "index" | "material"
) -> dict:
    """
    分析单张施工图，返回AI审核结果

    步骤：
    1. PDF页面 → 5张图
    2. CAD JSON → 坐标增强JSON
    3. 构造Prompt
    4. 调用Kimi
    5. 返回结果
    """

    # ── Step 1：生成5张图 ─────────────────────────────────────────────────────
    doc  = fitz.open(pdf_path)
    page = doc[page_index]
    images = pdf_page_to_5images(page)
    # images = {
    #   "full": bytes,
    #   "top_left": bytes, "top_right": bytes,
    #   "bottom_left": bytes, "bottom_right": bytes
    # }

    # 按固定顺序组成图片列表（图1全图，图2-5象限）
    image_list = [
        images["full"],
        images["top_left"],
        images["top_right"],
        images["bottom_left"],
        images["bottom_right"],
    ]

    # ── Step 2：坐标增强 ──────────────────────────────────────────────────────
    enriched_json = enrich_json_with_coordinates(layout_json)

    # ── Step 3：构造Prompt ────────────────────────────────────────────────────
    task_template = {
        "dimension": DIMENSION_AUDIT_TASK,
        "index":     INDEX_AUDIT_TASK,
        "material":  MATERIAL_AUDIT_TASK,
    }[audit_type]

    audit_task = task_template.format(
        sheet_no   = layout_json.get("sheet_no", ""),
        sheet_name = layout_json.get("layout_name", ""),
    )

    user_prompt = build_audit_prompt(
        enriched_json = enriched_json,
        audit_task    = audit_task,
        sheet_no      = layout_json.get("sheet_no", ""),
        sheet_name    = layout_json.get("layout_name", ""),
    )

    system_prompt = (
        "你是专业的室内装饰施工图审核专家，"
        "擅长识别施工图中的尺寸标注、索引符号和材料标注。"
        "只返回JSON格式结果，不要任何解释，不要markdown代码块。"
    )

    # ── Step 4：调用Kimi（5张图 + Prompt）────────────────────────────────────
    result = await call_kimi(
        system_prompt = system_prompt,
        user_prompt   = user_prompt,
        images        = image_list,   # 5张图
        temperature   = 0.1,
    )

    return result
```

---

## 九、数据流转总览

```
AutoLISP插件输出（原始JSON）
  └── layout_name, sheet_no, model_range
  └── dimensions[]: {id, value, text_position, layer}
  └── indexes[]:    {id, index_no, target_sheet, position}
  └── materials[]:  {id, code, name, position}
        ↓
enrich_json_with_coordinates()
  └── 每个数据点新增：
      global_pct:   {x: 38.2, y: 64.5}    ← 全图百分比
      grid:         "F11"                   ← 棋盘格坐标
      in_quadrants: {                       ← 象限归属+局部坐标
        "图4左下": {local_x_pct: 47.0, local_y_pct: 41.2}
      }
        ↓
pdf_page_to_5images()
  └── full:         带棋盘格的全图（4K内）
  └── top_left:     左上象限（3840px宽，20%重叠）
  └── top_right:    右上象限
  └── bottom_left:  左下象限
  └── bottom_right: 右下象限
        ↓
build_audit_prompt()
  └── 图片说明（5张图的关系和坐标系说明）
  └── 按象限分组的数据（每条数据含棋盘格+象限内坐标）
  └── 审核任务指令
        ↓
call_kimi(images=[5张图], user_prompt=prompt)
  └── Kimi步骤1-3：完整图像特征提取（整张A1空间感知）
  └── Kimi步骤4：语义理解阶段融合JSON数据
  └── Kimi步骤5：输出审核结论JSON
        ↓
审核结果存入 audit_results 表
```

---

## 十、关键参数说明与调优

| 参数 | 当前值 | 说明 | 调整建议 |
|------|--------|------|---------|
| `GRID_COLS` | 24 | 棋盘格列数（A-X） | 图纸标注极密集时可增至32 |
| `GRID_ROWS` | 17 | 棋盘格行数（1-17） | 与列数保持约1.4:1的宽高比 |
| `GRID_OVERLAP` | 0.20 | 象限重叠比例 | 标注密集时可增至0.25 |
| `TARGET_4K_W` | 3840 | Kimi最大支持宽度 | 随Kimi版本更新调整 |
| 全图DPI | 150 | 生成全图的源DPI | 不建议降低，否则细节损失 |
| 象限DPI | 300 | 生成象限图的源DPI | 不建议降低 |
| `temperature` | 0.1 | Kimi输出稳定性 | 不建议升高，避免数值被篡改 |
| `max_tokens` | 65536 | Kimi最大输出长度 | 保持最大值，防止JSON截断 |

---

*文档六：图纸图像处理与AI数据融合技术方案 V1.0 | 2026年2月*
*本文档描述的是整个系统中技术难度最高的核心模块，建议单独开发和测试，完全验证后再集成。*

"""
全局 AI 提示词配置服务。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from database import SessionLocal
from models import AIPromptSetting
from services.skill_pack_service import format_skill_rules_block, load_active_skill_rules

PLACEHOLDER_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


@dataclass(frozen=True)
class PromptStageDefinition:
    """提示词阶段的配置结构。"""

    stage_key: str
    title: str
    description: str
    call_site: str
    default_system_prompt: str
    default_user_prompt: str
    placeholders: tuple[str, ...] = ()


PROMPT_STAGE_DEFINITIONS: List[PromptStageDefinition] = [
    # ── 目录识别 ──────────────────────────────────────────────
    PromptStageDefinition(
        stage_key="catalog_recognition",
        title="目录识别",
        description="识别你上传的目录图，把每一行图号和图名整理出来。",
        call_site="上传目录后，系统会先跑这一段。",
        default_system_prompt="你是室内装饰施工图识别专家，只返回JSON，不要任何解释。",
        default_user_prompt=(
            "你将收到2张图：第1张是目录表左侧放大图（约占全图左侧46%宽度），第2张是全图。\n"
            "请以第1张为主提取所有目录条目，结合第2张纠正。\n"
            "只返回JSON数组，不要markdown，不要解释。\n"
            "每条记录字段固定为：图号、图名。\n"
            "图号需保留原样（例如 A1-01 / 02.03 / A4.02）。\n"
            "无法识别的字段填空字符串。\n"
            "输出时按图号出现顺序排列（从上到下）。\n"
            '输出示例：[{"图号":"A1-01","图名":"平面布置图"}]'
        ),
    ),
    # ── 单页图纸识别 ──────────────────────────────────────────
    PromptStageDefinition(
        stage_key="sheet_recognition",
        title="单页图纸识别",
        description="识别每一页图纸的图号和图名，帮助系统把 PDF 页和目录对上。",
        call_site="上传 PDF 图纸后，系统逐页跑这一段。",
        default_system_prompt="你是施工图识别Agent，只输出JSON。",
        default_user_prompt=(
            "你将收到同一页施工图的3张裁剪图：\n"
            "- 第1张：左侧（全图左34%）\n"
            "- 第2张：右侧（全图右34%）\n"
            "- 第3张：下方（全图下34%）\n"
            "请综合三张图，识别该页唯一的图号和图名。\n"
            "识别优先级：优先在第2张和第3张的重叠区域（右下角）查找图签。\n"
            "图号格式不固定，保留原样（如 A1-01、02.03、A4.02、S-01）。\n"
            "如果完全无法识别，图号和图名返回空字符串，置信度设0.0。\n"
            "只返回JSON对象，不要解释：\n"
            '{"图号":"","图名":"","置信度":0.0,"依据":""}'
        ),
    ),
    # ── 图纸识别汇总 ──────────────────────────────────────────
    PromptStageDefinition(
        stage_key="sheet_summarization",
        title="图纸识别汇总",
        description="对逐页识别结果做统一汇总纠偏，修复OCR误差。",
        call_site="图纸识别完成后，系统会跑这一段做全局校正。",
        default_system_prompt=(
            "你是施工图汇总Agent，负责对多页图纸识别结果进行统一校正。\n"
            "校正原则：\n"
            "1. 一致性：检查图号是否遵循统一编号规则（如都以A1-开头）\n"
            "2. 连续性：检查图号是否连续，发现跳号在理由中标注\n"
            "3. OCR纠错：修复明显的OCR误差（O/0混淆、I/1混淆、分隔符差异）\n"
            "只输出JSON。"
        ),
        default_user_prompt=(
            "请对输入的页级识别结果做统一汇总纠偏，输出每一页最终图号和图名。\n"
            "可修复轻微OCR误差，但不要凭空新增页。\n"
            '如果某页置信度低于0.5，在理由中标注"低置信度，建议人工复核"。\n'
            "输入JSON：\n"
            "{{payload_json}}\n"
            "只返回JSON数组，不要解释。\n"
            "数组每项格式："
            '{"page_index":0,"图号":"A1-01","图名":"平面布置图","置信度":0.0,"理由":""}'
        ),
        placeholders=("payload_json",),
    ),
    # ── 图纸目录匹配校验 ──────────────────────────────────────
    PromptStageDefinition(
        stage_key="sheet_catalog_validation",
        title="图纸目录匹配校验",
        description="将图纸识别结果与锁定目录做一对一匹配。",
        call_site="图纸汇总完成后，系统会跑这一段做最终匹配。",
        default_system_prompt=(
            "你是施工图匹配校验Agent，负责将图纸页与目录条目做一对一匹配。\n"
            "匹配策略（按优先级）：\n"
            "1. 图号精确匹配\n"
            "2. 图号模糊匹配（忽略分隔符差异、O/0混淆等）\n"
            "3. 图名+位置推断匹配\n"
            "每个page最多匹配一个catalog，每个catalog只能使用一次。\n"
            "只输出JSON。"
        ),
        default_user_prompt=(
            "请将 pages 与 catalog 做一对一匹配：每个 page 至多匹配一个 catalog，每个 catalog 只能使用一次。\n"
            "允许轻微OCR误差，优先图号，其次图名。\n"
            "如果无法匹配，对应字段留空字符串，置信度设0.0。\n"
            "输入JSON：\n"
            "{{payload_json}}\n"
            "只返回JSON数组，不要解释。\n"
            "数组每项格式："
            '{"page_index":0,"catalog_sheet_no":"A1-01","catalog_sheet_name":"平面布置图","置信度":0.0,"理由":""}'
        ),
        placeholders=("payload_json",),
    ),
    # ── 总控任务规划 ──────────────────────────────────────────
    PromptStageDefinition(
        stage_key="master_task_planner",
        title="总控任务规划",
        description="系统先决定先查哪些图、哪些图要互相对照，这一段负责排任务。",
        call_site="开始审核后，正式审图前会先跑这一段。",
        default_system_prompt=(
            "你是施工图审图总控 Agent，负责把输入图纸关系生成可执行任务图。"
            "必须只返回 JSON。"
        ),
        default_user_prompt=(
            "根据输入的图纸上下文和索引关系，生成审核任务列表。\n\n"
            "任务类型：\n"
            "- index：单图索引核对（只给 index_count>0 的图）\n"
            "- dimension：双图尺寸核对（严格来自 edges 的 source->target）\n"
            "- material：双图材料核对（严格来自 edges 的 source->target）\n\n"
            "规划原则：\n"
            '- 所有图号必须来自输入 contexts.sheet_no，不能编造\n'
            '- 平面图（A1开头/含"平面"）优先级更高（1-2级），其他图3-4级\n'
            "- 同一任务不能重复（task_type + source_sheet_no + target_sheet_no）\n"
            "- 对每个有效 edge，至少生成 1 条 dimension 和 1 条 material 任务\n"
            "- 对每个 index_count>0 的图，至少生成 1 条 index 任务\n\n"
            "输出JSON对象：\n"
            "{\n"
            '  "tasks":[\n'
            "    {\n"
            '      "task_type":"index|dimension|material",\n'
            '      "source_sheet_no":"",\n'
            '      "target_sheet_no":"",\n'
            '      "priority":1,\n'
            '      "reason":"",\n'
            '      "evidence":{"path":"", "edge_mention_count":0}\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "输入数据如下（JSON）：\n"
            "{{payload_json}}\n"
        ),
        placeholders=("payload_json",),
    ),
    # ── 尺寸单图语义分析 ──────────────────────────────────────
    PromptStageDefinition(
        stage_key="dimension_single_sheet",
        title="尺寸单图语义分析",
        description="先读懂一张图里每个尺寸大概在说什么，给后面的跨图对比打基础。",
        call_site="尺寸审核时，系统会先对单张图跑这一段。",
        default_system_prompt=(
            "你是专业施工图审核专家，擅长结合全图与象限图做尺寸语义解析。\n\n"
            "施工图基本知识：\n"
            "- 尺寸链从外到内依次为总尺寸→分段尺寸→细部尺寸\n"
            "- 轴线通常标注为横向①②③...、纵向A B C...\n\n"
            "坐标系说明（重要）：\n"
            "- 使用百分比坐标 global_pct 定位：x=0 最左，x=100 最右，y=0 最上，y=100 最下\n"
            "- 象限图外围有白色边距，边距上标有百分比刻度尺，这是坐标参考工具\n"
            "- 图纸内容只在白色边距以内，刻度尺本身不是图纸的一部分\n"
            "- 你输出的 global_pct 必须是全图百分比坐标，与 JSON 数据中的 global_pct 是同一坐标系\n\n"
            "只返回JSON数组，不要解释。"
        ),
        default_user_prompt=(
            "对图纸（{{sheet_no}} {{sheet_name}}）做尺寸语义分析。\n\n"
            "你将收到5张图：\n"
            "- 图1：完整施工图全图（200 DPI 总览）\n"
            "- 图2-5：四个象限的高清图（300 DPI），外围有白色边距，边距上标有百分比刻度尺\n"
            "  - 图2 左上象限（覆盖全图 X:0%-60%, Y:0%-60%）\n"
            "  - 图3 右上象限（覆盖全图 X:40%-100%, Y:0%-60%）\n"
            "  - 图4 左下象限（覆盖全图 X:0%-60%, Y:40%-100%）\n"
            "  - 图5 右下象限（覆盖全图 X:40%-100%, Y:40%-100%）\n"
            "相邻象限有20%重叠，确保边界处标注不被截断。\n\n"
            "**坐标读取方法：** 看象限图白色边距上的刻度数字，即可得到该位置的全图百分比坐标。\n"
            "刻度坐标与 JSON 数据中的 global_pct 是完全一致的坐标系，可直接对应。\n\n"
            "以下是DWG提取的精确尺寸数据（数值100%准确，无需重新OCR）。\n"
            "每条数据字段说明：\n"
            "- id：标注唯一ID\n"
            "- value：精确数值（mm）\n"
            "- display_text：标注显示文字\n"
            "- global_pct：在全图中的百分比位置（x=0最左, x=100最右, y=0最上, y=100最下）\n"
            "- in_quadrants：该标注在哪些象限图（图2-5）中可见\n\n"
            "数据：\n"
            "{{dims_compact_json}}\n\n"
            "分析步骤：\n"
            "1. 根据 global_pct 百分比坐标在全图中定位每条尺寸的大致区域\n"
            "2. 根据 in_quadrants 找到对应的高清象限图，确认标注上下文\n"
            "3. 判断每条尺寸标注的对象和类型\n\n"
            "尺寸类型（填入 dim_type）：\n"
            '- "总尺寸"：房间或空间的总长度/宽度\n'
            '- "分段尺寸"：构成总尺寸的各段\n'
            '- "定位尺寸"：构件相对于轴线的距离\n'
            '- "细部尺寸"：局部详图中的精确尺寸\n'
            '- "标高"：竖向高度标注\n\n'
            "请输出每条尺寸的语义解析结果，只返回JSON数组，不要解释。\n"
            "格式："
            '[{"id":"","semantic":"","location_desc":"","dim_type":"","value":0,'
            '"global_pct":{"x":0,"y":0},"component":"","confidence":0.0,"evidence":{"global_pct":{"x":0,"y":0},"why":""}}]'
        ),
        placeholders=("sheet_no", "sheet_name", "dims_compact_json"),
    ),
    # ── 尺寸纯视觉分析（无JSON辅助）────────────────────────────
    PromptStageDefinition(
        stage_key="dimension_visual_only",
        title="尺寸纯视觉分析",
        description="当 DXF 提取无尺寸数据时，AI 纯视觉读取图纸中的所有尺寸标注。",
        call_site="尺寸审核时，对无 JSON 尺寸数据的图纸跑这一段。",
        default_system_prompt=(
            "你是专业施工图审核专家，擅长通过视觉分析识别和提取图纸中的尺寸标注。\n\n"
            "施工图基本知识：\n"
            "- 尺寸链从外到内依次为总尺寸→分段尺寸→细部尺寸\n"
            "- 轴线通常标注为横向①②③...、纵向A B C...\n\n"
            "坐标系说明（重要）：\n"
            "- 使用百分比坐标 global_pct 定位：x=0 最左，x=100 最右，y=0 最上，y=100 最下\n"
            "- 象限图外围有白色边距，边距上标有百分比刻度尺，这是坐标参考工具\n"
            "- 图纸内容只在白色边距以内，刻度尺本身不是图纸的一部分\n"
            "- 你输出的 global_pct 必须是全图百分比坐标\n\n"
            "你必须通过视觉识别图纸中的所有尺寸标注，包括数值、位置和含义。\n\n"
            "只返回JSON数组，不要解释。"
        ),
        default_user_prompt=(
            "对图纸（{{sheet_no}} {{sheet_name}}）做纯视觉尺寸分析。\n\n"
            "**注意：本图没有 DXF 提取的尺寸数据，你需要完全通过图片来识别尺寸。**\n\n"
            "你将收到5张图：\n"
            "- 图1：完整施工图全图（200 DPI 总览）\n"
            "- 图2-5：四个象限的高清图（300 DPI），外围有白色边距，边距上标有百分比刻度尺\n"
            "  - 图2 左上象限（覆盖全图 X:0%-60%, Y:0%-60%）\n"
            "  - 图3 右上象限（覆盖全图 X:40%-100%, Y:0%-60%）\n"
            "  - 图4 左下象限（覆盖全图 X:0%-60%, Y:40%-100%）\n"
            "  - 图5 右下象限（覆盖全图 X:40%-100%, Y:40%-100%）\n"
            "相邻象限有20%重叠，确保边界处标注不被截断。\n\n"
            "**坐标读取方法：** 看象限图白色边距上的刻度数字，即可得到该位置的全图百分比坐标。\n"
            "只分析白色边距以内的图纸内容，刻度尺不是图纸的一部分。\n\n"
            "分析步骤：\n"
            "1. 在各象限高清图中逐区域扫描白色边距以内的图纸，找到所有可见的尺寸标注\n"
            "2. 根据象限图白色边距上的百分比刻度确定每条尺寸在全图中的百分比位置\n"
            "3. 读取尺寸数值（数字+单位）\n"
            "4. 判断每条尺寸标注的对象和类型\n\n"
            "尺寸类型（填入 dim_type）：\n"
            '"总尺寸"：房间或空间的总长度/宽度\n'
            '"分段尺寸"：构成总尺寸的各段\n'
            '"定位尺寸"：构件相对于轴线的距离\n'
            '"细部尺寸"：局部详图中的精确尺寸\n'
            '"标高"：竖向高度标注\n\n'
            "请输出每条发现的尺寸，只返回JSON数组，不要解释。\n"
            "格式："
            '[{"id":"visual_001","semantic":"","location_desc":"","dim_type":"","value":0,'
            '"global_pct":{"x":0,"y":0},"component":"","confidence":0.0,"evidence":{"global_pct":{"x":0,"y":0},"why":""}}]'
        ),
        placeholders=("sheet_no", "sheet_name"),
    ),
    # ── 尺寸双图对比 ──────────────────────────────────────────
    PromptStageDefinition(
        stage_key="dimension_pair_compare",
        title="尺寸双图对比",
        description="把两张相关图里的尺寸一一对上，找出互相打架的地方。",
        call_site="尺寸审核时，单图分析完成后会跑这一段。",
        default_system_prompt=(
            "你是施工图尺寸一致性审核专家。"
            "你会基于两张图的尺寸语义列表和图片做交叉核对。\n\n"
            "坐标说明：所有 global_pct 坐标均为全图百分比坐标（x=0最左, x=100最右, y=0最上, y=100最下）。\n"
            "如果收到图片，图片可能带有白色边距和百分比刻度尺，只分析边距以内的图纸内容。\n\n"
            "差异判断标准：\n"
            "- 差值=0：完全一致，不输出\n"
            "- 0 < 差值 ≤ 3mm：工程精度内偏差，不输出\n"
            "- 3mm < 差值 ≤ 10mm：可能的标注精度差异，confidence 标 0.3-0.5\n"
            "- 差值 > 10mm：大概率不一致，confidence 标 0.7+\n"
            "- 注意单位：2400mm 和 2.4m 是同一尺寸，不是不一致\n\n"
            "只返回JSON数组，不要解释。"
        ),
        default_user_prompt=(
            "请对比两张图的尺寸语义列表，找出同一构件/空间的尺寸不一致项。\n"
            "你必须按流程执行：先定位 -> 再配对 -> 再核对。\n\n"
            "配对策略（按优先级）：\n"
            "1. global_pct 坐标匹配：两图中百分比位置接近的尺寸优先配对\n"
            "2. component 语义匹配：描述相同构件的尺寸配对\n"
            "3. 数值接近匹配：相同区域内数值接近的尺寸配对\n\n"
            "规则：\n"
            "1) 先根据 semantic/component/global_pct 选候选，不要直接猜。\n"
            "2) 只有定位证据充分时才输出问题；证据不足就不要输出。\n"
            "3) 输出必须带证据字段，便于人工复核。\n\n"
            "A图：{{a_sheet_no}} {{a_sheet_name}}\n"
            "A图语义数据：{{a_semantic_json}}\n"
            "B图：{{b_sheet_no}} {{b_sheet_name}}\n"
            "B图语义数据：{{b_semantic_json}}\n\n"
            "只返回问题JSON数组，无问题返回[]。\n"
            "格式：[{"
            '"位置描述":"",'
            '"A图号":"","B图号":"",'
            '"A值":0,"B值":0,"差值":0,'
            '"source_pct":{"x":0,"y":0},"target_pct":{"x":0,"y":0},'
            '"source_dim_id":"","target_dim_id":"",'
            '"index_hint":"",'
            '"confidence":0.0,'
            '"description":"",'
            '"evidence":{'
            '"source_sheet_no":"","target_sheet_no":"",'
            '"source_pct":{"x":0,"y":0},"target_pct":{"x":0,"y":0},'
            '"source_dim_id":"","target_dim_id":"",'
            '"confidence":0.0,"why":""'
            "}"
            "}]"
        ),
        placeholders=(
            "a_sheet_no",
            "a_sheet_name",
            "a_semantic_json",
            "b_sheet_no",
            "b_sheet_name",
            "b_semantic_json",
        ),
    ),
    # ── AI 关系发现 ──────────────────────────────────────────
    PromptStageDefinition(
        stage_key="sheet_relationship_discovery",
        title="图纸关系发现",
        description="AI 视觉分析图纸，自动发现跨图引用关系（索引、详图引用、剖面引用等）。",
        call_site="审核开始时，构建图纸上下文后、规划审核任务前执行。",
        default_system_prompt=(
            "你是专业施工图索引关系识别专家。\n\n"
            "你的任务是通过视觉分析施工图，识别所有跨图引用关系。\n\n"
            "施工图索引符号知识：\n"
            "- 索引符号通常是圆圈，上方为详图编号，下方为目标图号\n"
            "- 下方为短横线（-、—）表示本图索引，不是跨图引用\n"
            "- 详图标签是圆圈内的编号+图号组合\n"
            "- 剖面/断面符号指向其他图纸\n"
            "- 放大区域标记指向详图\n\n"
            "坐标系说明（重要）：\n"
            "- 使用百分比坐标 global_pct 定位：x=0 最左，x=100 最右，y=0 最上，y=100 最下\n"
            "- 象限图外围有白色边距，边距上标有百分比刻度尺，这是坐标参考工具\n"
            "- 图纸内容只在白色边距以内，刻度尺不是图纸的一部分\n"
            "- 你输出的 global_pct 必须是全图百分比坐标，与 JSON 数据中的坐标是同一坐标系\n\n"
            "只返回JSON数组，不要解释。"
        ),
        default_user_prompt=(
            "请分析以下图纸，找出所有跨图引用关系。\n\n"
            "{{discovery_prompt}}"
        ),
        placeholders=("discovery_prompt",),
    ),
    # ── 材料一致性审核 ────────────────────────────────────────
    PromptStageDefinition(
        stage_key="material_consistency_review",
        title="材料一致性审核",
        description="根据材料表与图纸材料标注，识别语义冲突、别名误配与上下文不一致。",
        call_site="材料审核时，系统会对每张图的材料表和材料标注跑这一段。",
        default_system_prompt=(
            "你是施工图材料一致性审核专家。\n"
            "你需要结合材料编号、材料名称和表达上下文，识别真正需要人工复核的问题。\n\n"
            "输出规则：\n"
            "1. 只返回 JSON 数组，不要解释\n"
            "2. 没有问题返回 []\n"
            "3. 明显同义词、简称、常见省略表达，不要误报\n"
            "4. 只有在材料名称语义冲突、编号可能错配、或表中定义与图中使用关系异常时才输出\n"
        ),
        default_user_prompt=(
            "请审核图纸 {{sheet_no}} 的材料一致性。\n\n"
            "材料表：{{material_table_json}}\n\n"
            "图纸材料标注：{{material_used_json}}\n\n"
            "请只输出需要人工复核的问题，格式："
            '[{"severity":"warning","location":"","material_code":"","confidence":0.0,'
            '"description":"","evidence":{"code":"","grid":"","why":""}}]'
        ),
        placeholders=("sheet_no", "material_table_json", "material_used_json"),
    ),
]

PROMPT_STAGE_MAP: Dict[str, PromptStageDefinition] = {
    item.stage_key: item for item in PROMPT_STAGE_DEFINITIONS
}


def get_prompt_stage_definition(stage_key: str) -> PromptStageDefinition:
    """根据阶段键获取提示词阶段定义。"""
    definition = PROMPT_STAGE_MAP.get(stage_key)
    if not definition:
        raise KeyError(f"unknown_prompt_stage:{stage_key}")
    return definition


def _load_override_map(db) -> Dict[str, AIPromptSetting]:  # noqa: ANN001
    """从数据库加载所有提示词覆盖配置映射。"""
    rows = db.query(AIPromptSetting).all()
    return {row.stage_key: row for row in rows}


def _serialize_stage(
    definition: PromptStageDefinition,
    override: Optional[AIPromptSetting],
) -> Dict[str, Any]:
    """将提示词阶段定义序列化为字典格式。"""
    current_system = (
        override.system_prompt_override
        if override and override.system_prompt_override is not None
        else definition.default_system_prompt
    )
    current_user = (
        override.user_prompt_override
        if override and override.user_prompt_override is not None
        else definition.default_user_prompt
    )
    is_overridden = bool(
        override
        and (
            override.system_prompt_override is not None
            or override.user_prompt_override is not None
        )
    )
    return {
        "stage_key": definition.stage_key,
        "title": definition.title,
        "description": definition.description,
        "call_site": definition.call_site,
        "system_prompt": current_system,
        "user_prompt": current_user,
        "default_system_prompt": definition.default_system_prompt,
        "default_user_prompt": definition.default_user_prompt,
        "is_overridden": is_overridden,
        "placeholders": list(definition.placeholders),
        "updated_at": override.updated_at.isoformat()
        if override and override.updated_at
        else None,
    }


def list_prompt_stages(db) -> Dict[str, List[Dict[str, Any]]]:  # noqa: ANN001
    """列出所有提示词阶段及其配置。"""
    overrides = _load_override_map(db)
    return {
        "stages": [
            _serialize_stage(definition, overrides.get(definition.stage_key))
            for definition in PROMPT_STAGE_DEFINITIONS
        ]
    }


def upsert_prompt_stages(
    db, stages: List[Dict[str, str]]
) -> Dict[str, List[Dict[str, Any]]]:  # noqa: ANN001
    """批量更新或插入提示词阶段配置。"""
    override_map = _load_override_map(db)
    now = datetime.now()
    for item in stages:
        stage_key = str(item.get("stage_key") or "").strip()
        if stage_key not in PROMPT_STAGE_MAP:
            raise ValueError(f"unknown_prompt_stage:{stage_key}")
        row = override_map.get(stage_key)
        if row is None:
            row = AIPromptSetting(stage_key=stage_key)
            db.add(row)
            override_map[stage_key] = row
        row.system_prompt_override = item.get("system_prompt")
        row.user_prompt_override = item.get("user_prompt")
        row.updated_at = now
    db.commit()
    return list_prompt_stages(db)


def reset_prompt_stage(db, stage_key: str) -> Dict[str, Any]:  # noqa: ANN001
    """重置提示词阶段为默认配置。"""
    if stage_key not in PROMPT_STAGE_MAP:
        raise ValueError(f"unknown_prompt_stage:{stage_key}")
    row = (
        db.query(AIPromptSetting).filter(AIPromptSetting.stage_key == stage_key).first()
    )
    if row:
        db.delete(row)
        db.commit()
    override = None
    return _serialize_stage(get_prompt_stage_definition(stage_key), override)


def _render_template(template: str, variables: Dict[str, Any]) -> str:
    """渲染提示词模板，替换占位符变量。"""
    if variables is None:
        variables = {}

    missing: List[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            missing.append(key)
            return match.group(0)
        value = variables[key]
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    rendered = PLACEHOLDER_PATTERN.sub(replace, template)
    if missing:
        joined = ",".join(sorted(set(missing)))
        raise ValueError(f"missing_prompt_placeholders:{joined}")
    return rendered


def resolve_stage_prompts(
    stage_key: str, variables: Optional[Dict[str, Any]] = None
) -> Dict[str, str]:
    """解析指定阶段的提示词（系统和用户提示词），支持变量替换。"""
    session = SessionLocal()
    try:
        definition = get_prompt_stage_definition(stage_key)
        row = (
            session.query(AIPromptSetting)
            .filter(AIPromptSetting.stage_key == stage_key)
            .first()
        )
        system_prompt = (
            row.system_prompt_override
            if row and row.system_prompt_override is not None
            else definition.default_system_prompt
        )
        user_prompt = (
            row.user_prompt_override
            if row and row.user_prompt_override is not None
            else definition.default_user_prompt
        )
    finally:
        session.close()

    rendered_system = _render_template(system_prompt, variables or {})
    rendered_user = _render_template(user_prompt, variables or {})
    return {"system_prompt": rendered_system, "user_prompt": rendered_user}


def resolve_stage_system_prompt(stage_key: str) -> str:
    """解析指定阶段的系统提示词。"""
    session = SessionLocal()
    try:
        definition = get_prompt_stage_definition(stage_key)
        row = (
            session.query(AIPromptSetting)
            .filter(AIPromptSetting.stage_key == stage_key)
            .first()
        )
        system_prompt = (
            row.system_prompt_override
            if row and row.system_prompt_override is not None
            else definition.default_system_prompt
        )
    finally:
        session.close()
    return _render_template(system_prompt, {})


def resolve_stage_system_prompt_with_skills(
    stage_key: str,
    skill_type: str,
) -> str:
    """解析指定阶段系统提示词，并追加启用的技能包规则。"""
    session = SessionLocal()
    try:
        definition = get_prompt_stage_definition(stage_key)
        row = (
            session.query(AIPromptSetting)
            .filter(AIPromptSetting.stage_key == stage_key)
            .first()
        )
        system_prompt = (
            row.system_prompt_override
            if row and row.system_prompt_override is not None
            else definition.default_system_prompt
        )
        rules = load_active_skill_rules(
            session,
            skill_type=skill_type,
            stage_key=stage_key,
        )
    finally:
        session.close()

    rendered_system = _render_template(system_prompt, {})
    rules_block = format_skill_rules_block(rules)
    if not rules_block:
        return rendered_system
    return f"{rendered_system}\n\n{rules_block}"

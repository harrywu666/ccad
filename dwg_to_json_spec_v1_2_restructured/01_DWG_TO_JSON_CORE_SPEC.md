
# DWG→JSON Core Spec（核心规范）


> 版本：v1.2  
> 来源：基于 `DWG_TO_JSON_SPEC_v1.2.md` 重组  
> 目的：把“核心规范 / 扩展专题 / 实现说明 / LLM 消费说明”分层，便于开发团队、Codex、Claude Code 分阶段执行。  
>
> 规范级别说明：
> - **MUST**：当前系统必须满足
> - **SHOULD**：强烈建议满足，可在后续迭代补齐
> - **MAY**：可选扩展，不应阻塞当前里程碑


本文件只保留 **DWG→JSON 的核心表示规范**。阅读顺序建议：先读本文件，再读《Implementation Notes》，最后按需要查阅《Extensions》与《LLM Consumption Notes》。  

本文件中的内容默认以 **MUST** 为主；若章节内出现更细的约束级别，以小节说明为准。

## 核心约束（摘要）

1. **MUST** 采用分层 JSON，而不是单层“大 JSON”。
2. **MUST** 同时保留 model space / paper space / viewport / canonical 几何与来源关系。
3. **MUST** 将标注真值独立建模，不得用几何长度直接替代显示尺寸。
4. **MUST** 为所有高层语义对象保留 `source_entity_ids`、`confidence` 与证据链。
5. **MUST** 显式支持 `ReviewView` 与 `LogicalSheet`，不得把 `Layout` 直接当作最终图纸。
6. **MUST** 对 XREF 缺失、动态块降级、字体回退、文本缺失等情况输出可追溯降级信息。
7. **MUST NOT** 直接把 Raw CAD JSON 作为 LLM 审图主输入。
## 1. 文档目标

这份文档解决的不是“DWG 能不能导成 JSON”，而是：

**DWG 应该被转换成什么结构的 JSON，才能支撑室内施工图 AI 审图。**

重点包括：

- 如何保留 DWG 原始信息，避免后续无法追溯
- 如何兼容不同公司的绘图习惯
- 如何同时处理 model space / paper space
- 如何支持一布局一图、一布局多图
- 如何处理尺寸显示值与真实几何值冲突
- 如何为平面 / 天花 / 地坪 / 节点 / 立面建立跨图关系
- 如何为规则引擎和 LLM 提供稳定、可解释的输入

一句话：

> DWG 转 JSON 的目标不是“换一种格式保存 CAD”，而是“构建 AI 审图系统的数据底座”。

---

## 2. 一句话结论

DWG 转 JSON **必须分层**，至少分成四层：

1. **Raw CAD JSON**：底层保真层  
2. **Normalized CAD JSON**：统一工程层  
3. **Semantic Review JSON**：审图语义层  
4. **Evidence / Truth JSON**：证据与真值层

**不要把 Raw CAD JSON 直接喂给 LLM 做审图。**  
Raw 层负责保真，Semantic + Evidence 层才是 AI 审图的主输入。

---

## 3. 术语定义

### 3.1 Document
一个原始 DWG 文件对应一个 `document`。

### 3.2 Model Space
模型空间。通常按 1:1 真实尺寸绘制，几何主体多在这里。

### 3.3 Paper Space / Layout
布局空间 / 纸空间。常用于图框、标题、图号、比例、说明、纸空间尺寸、视口等。

### 3.4 Viewport
布局空间中的视口。它决定了布局里看到的是模型空间的哪一部分、按什么比例显示。

### 3.5 ReviewView
系统抽象出的“可审图区域”。不是 CAD 原生概念，是 AI 审图系统的重要中间层。

### 3.6 LogicalSheet
系统认定的一张“逻辑图纸”。它不一定等于一个 layout，也不一定等于一页 PDF。

### 3.7 Raw Entity
CAD 底层对象，例如 `LINE / LWPOLYLINE / TEXT / MTEXT / INSERT / DIMENSION / TABLE / VIEWPORT`。

### 3.8 Semantic Object
审图语义对象，例如 `Space / Door / CeilingZone / LevelMark / WetArea / DetailCallout`。

---

## 4. 设计原则

### 4.1 保真优先，语义后置
先完整保留原始 CAD 信息，再做语义抽象。不要一开始就把图元强判成“门/墙/吊顶”。

### 4.2 任何高层对象都必须可追溯
每个语义对象必须能追溯到：

- 源 document
- 源 layout / page
- 源 raw entity ids
- 坐标变换链
- 解析置信度

### 4.3 Layout 不等于图纸
一个 layout 可能一张图，也可能多张图。必须引入：

- Layout
- ReviewView
- LogicalSheet

### 4.4 坐标必须分层
至少要明确：

- model space 坐标
- paper space 坐标
- viewport 变换
- canonical review 坐标

### 4.5 标注真值必须双轨
必须同时保留：

- `display_value`（显示值）
- `measured_value`（尺寸对象测量值）
- `computed_value`（几何反算值）
- `is_override`
- `source_space`

### 4.6 为规则引擎服务
JSON 不是给前端“画一下”就完了，而是要支撑：

- 规则执行
- 跨图关系图谱
- 证据链追溯
- LLM 问答与报告生成

### 4.7 允许不确定性
每个对象和关系都应允许：

- `confidence`
- `extraction_basis`
- `alternative_candidates`
- `degraded_reason`

---

## 6. 四层 JSON 结构

### 6.1 Raw CAD JSON
职责：最大限度保留 DWG 原始信息。

至少应包含：

- document metadata
- layouts
- layers
- block definitions
- raw entities
- text styles / dim styles
- xrefs

### 6.2 Normalized CAD JSON
职责：把不同类型对象统一成便于程序处理的结构。

统一内容：

- `id`
- `space`
- `bbox`
- `transform`
- `style_ref`
- `source_entity_ids`
- `owner_layout_id`

### 6.3 Semantic Review JSON
职责：表达审图语义对象。

至少应包括：

- `Space`
- `Wall`
- `Door`
- `CeilingZone`
- `FloorFinishZone`
- `LevelMark`
- `DetailCallout`
- `ElevationCallout`
- `WetArea`
- `WaterproofZone`
- `DrainMark`
- `SlopeMark`
- `DoorSchedule`
- `FinishSchedule`
- `ConstructionMethodTable`

### 6.4 Evidence / Truth JSON
职责：表达设计意图、冲突状态和证据链。

至少应包括：

- `DimensionEvidence`
- `LevelEvidence`
- `TextEvidence`
- `RelationshipEvidence`
- `RuleEvidence`

---

## 7. Raw CAD JSON 详细规范

### 7.1 document

```json
{
  "document_id": "DOC-001",
  "source_path": "sample_room.dwg",
  "file_hash": "sha256:...",
  "unit": "mm",
  "document_title": "样板房精装修施工图",
  "parser": {
    "engine": "oda_or_other",
    "engine_mode": "desktop_preprocess_or_sdk",
    "warnings": []
  },
  "parse_time": "2026-03-13T10:00:00Z"
}
```

### 7.2 layouts

```json
{
  "layout_id": "LAYOUT-01",
  "name": "A1",
  "tab_order": 1,
  "paper_size": {"width": 841, "height": 594, "unit": "mm"},
  "origin": [0, 0],
  "rotation_deg": 0,
  "space_type": "paper_space"
}
```

### 7.3 layer

```json
{
  "layer_id": "LAYER-001",
  "name": "A-WALL",
  "is_frozen": false,
  "is_locked": false,
  "is_off": false,
  "color": 7,
  "linetype": "Continuous",
  "lineweight": "Default"
}
```

### 7.4 block definition

```json
{
  "block_id": "BLK-DOOR-01",
  "name": "DOOR_SINGLE",
  "base_point": [0,0],
  "entity_ids": ["E1", "E2", "E3"]
}
```

### 7.5 raw entity

```json
{
  "entity_id": "E-001",
  "handle": "1A2B",
  "type": "LWPOLYLINE",
  "space": "model_space",
  "owner_layout_id": null,
  "layer": "A-WALL",
  "visibility": true,
  "geometry": {
    "vertices": [[0,0],[1000,0],[1000,100],[0,100]],
    "closed": true
  },
  "raw_properties": {}
}
```

---

## 8. 必须支持的原始对象类型

### 8.1 基础几何
- LINE
- LWPOLYLINE
- POLYLINE
- ARC
- CIRCLE
- ELLIPSE
- SPLINE
- HATCH
- SOLID

### 8.2 文本
- TEXT
- MTEXT
- ATTRIB
- ATTDEF

### 8.3 尺寸与引线
- DIMENSION
- LEADER
- MLEADER

### 8.4 复合对象
- INSERT
- BLOCK_REFERENCE
- DYNAMIC BLOCK（若可识别）

### 8.5 表格与版面对象
- TABLE
- VIEWPORT
- IMAGE / UNDERLAY（如存在）

### 8.6 外部依赖
- XREF

如果某类对象暂时无法可靠解析，也必须保留一个“未展开对象”的 stub，而不要静默丢弃。

---

## 9. 为什么 model space / paper space 都必须进入 JSON

真实项目里常见情况：

- 模型空间负责绘图本体
- 布局空间负责图框、标题、比例、图号、索引、尺寸、说明

同时还存在很多“设计师习惯差异”：

- 有些尺寸在模型空间标
- 有些尺寸只在布局空间标
- 有些说明文字只在布局空间
- 有些图号、图名、节点编号只在布局空间
- 有些公司一个 layout 一张图
- 有些公司一个 layout 多张图

如果只抽 model space，会丢掉很多关键设计意图。  
如果只抽 paper space，会丢掉真实几何和构件关系。

所以：

> DWG->JSON 必须同时保留 model space 与 paper space，并通过 viewport 建立连接。

---

## 10. 坐标系统规范

### 10.1 为什么不能只存一个坐标
因为对象可能来自：

- model space
- paper space
- viewport 映射区域
- 统一审图空间

如果只存一个 `position`，后面会分不清：

- 这个尺寸是在纸上量出来的还是在模型里画出来的
- 这个标题是纸空间元素，还是模型文字
- 这个对象如何与另一个页 / 另一个 ReviewView 对齐

### 10.2 推荐坐标层
- `raw_model_geometry`
- `raw_paper_geometry`
- `viewport_transform`
- `canonical_geometry`

### 10.3 transform 结构建议

```json
{
  "transform_id": "TF-001",
  "from_space": "model_space",
  "to_space": "paper_space",
  "layout_id": "LAYOUT-01",
  "viewport_id": "VP-01",
  "scale": 0.02,
  "rotation_deg": 0,
  "translation": [120, 80],
  "confidence": 0.98
}
```

### 10.4 canonical review coordinate
建议每个 ReviewView 都有本地统一坐标：

```json
{
  "review_view_id": "RV-101",
  "canonical_bbox": [0,0,5000,3200],
  "canonical_unit": "mm"
}
```

这样同一个 ReviewView 内的标题、尺寸、房间边界、门、灯位、节点索引都可以在同一套坐标中计算。

---

## 11. Layout / Viewport / ReviewView / LogicalSheet 的 JSON 设计

### 11.1 Layout 不是图纸
布局只是容器。

### 11.2 ReviewView 是“可审图区域”

```json
{
  "review_view_id": "RV-001",
  "layout_id": "LAYOUT-01",
  "source_page_id": "PAGE-03",
  "bbox_in_paper": [100, 100, 600, 450],
  "title_candidates": ["主卧平面布置图"],
  "sheet_number_candidates": ["A-101"],
  "sheet_type_candidates": ["floor_plan"],
  "viewport_ids": ["VP-01"],
  "paper_entity_ids": ["TXT-01", "DIM-05"],
  "confidence": 0.84
}
```

### 11.3 LogicalSheet 是“逻辑图纸”

```json
{
  "logical_sheet_id": "LS-001",
  "source_page_ids": ["PAGE-03"],
  "review_view_ids": ["RV-001"],
  "sheet_number": "A-101",
  "sheet_title": "平面布置图",
  "sheet_type": "floor_plan",
  "floor_or_level": "L1",
  "confidence": 0.87,
  "extraction_basis": {
    "title": "平面布置图",
    "sheet_number": "A-101",
    "page_type": "floor_plan"
  }
}
```

### 11.4 必须允许一页多图
对于一页多图的情况：

- `1 page -> N review_views`
- `N review_views -> N logical_sheets`（多数情况）

---

## 12. 标注与尺寸：必须单独建模

### 12.1 室内施工图中“真实尺寸”和“显示尺寸”经常不一致
例如：

- 模型几何长度约 800
- 尺寸对象测量值 800
- 但设计师在布局空间中手改显示为 1000

这时：

- 如果只看几何，会误判设计意图
- 如果只看显示值，会漏掉图模不一致问题

### 12.2 DimensionEvidence 结构

```json
{
  "dimension_id": "DIM-001",
  "source_entity_id": "E-888",
  "source_space": "paper_space",
  "dimension_type": "aligned",
  "display_text_raw": "1000",
  "display_value": 1000,
  "measured_value": 800,
  "computed_value": 798.6,
  "unit": "mm",
  "is_override": true,
  "truth_role": "design_intent",
  "conflict_status": "conflict",
  "owner_review_view_id": "RV-001",
  "linked_geometry_entity_ids": ["E-101", "E-102"],
  "confidence": 0.94
}
```

### 12.3 真值策略

#### 设计意图主值
优先看：

- `display_value`
- 尤其是布局空间尺寸
- 尤其是节点 / 详图中的手改文字

#### 一致性校核副值
同时保留：

- `measured_value`
- `computed_value`

并对以下情况单独出问题：

- 显示值与测量值偏差过大
- 显示值与几何值偏差过大
- override 但无可对应几何
- 节点图与平面图尺寸冲突

### 12.4 正式产品化表述
建议写成：

> 以最终显示给施工与审图人员的标注值作为设计意图主值；以尺寸对象测量值与几何反算值作为一致性校核副值。

---

## 13. 文本、标题、图号、比例、表格必须单独考虑

### 13.1 文本不是附属信息
很多关键语义都来自文字：

- 房间名
- 图名
- 图号
- 标高
- 材料编号
- 节点编号
- 说明文字
- 表格内容

### 13.2 TextEvidence 结构建议

```json
{
  "text_id": "TXT-001",
  "source_entity_id": "E-201",
  "space": "paper_space",
  "text_type_candidates": ["sheet_title", "annotation"],
  "content": "主卧平面布置图",
  "position": [120, 60],
  "bbox": [100, 50, 180, 70],
  "rotation_deg": 0,
  "owner_review_view_id": "RV-001"
}
```

### 13.3 表格不能只当作文字堆
门表、材料表、做法表、图纸目录表都应尽可能结构化。

```json
{
  "table_id": "TB-001",
  "table_type": "door_schedule",
  "source_space": "paper_space",
  "owner_review_view_id": "RV-010",
  "bbox": [50,50,300,400],
  "columns": ["mark", "width", "height", "material"],
  "rows": [
    {
      "row_key": "D03",
      "cells": {
        "mark": "D03",
        "width": "800",
        "height": "2100",
        "material": "WD-01"
      }
    }
  ],
  "source_entity_ids": ["E-301"]
}
```

---

## 14. 块（Block / Insert）如何进入 JSON

### 14.1 为什么块很关键
室内图里大量语义对象来自块：

- 门
- 洁具
- 家具
- 灯具
- 开关插座
- 地漏
- 索引符号
- 立面符号
- 剖切符号

### 14.2 BlockDefinition 与 Insert 必须分离
- `BlockDefinition`：定义是什么
- `Insert / BlockReference`：表示用了哪里、如何变换、带了什么属性

### 14.3 Insert 结构建议

```json
{
  "insert_id": "INS-001",
  "source_entity_id": "E-501",
  "block_name": "DOOR_SINGLE",
  "space": "model_space",
  "position": [1200, 3400],
  "rotation_deg": 90,
  "scale": [1,1,1],
  "attributes": {
    "MARK": "D03",
    "WIDTH": "800"
  },
  "owner_layout_id": null,
  "source_block_id": "BLK-DOOR-01",
  "confidence": 1.0
}
```

### 14.4 建议增加块适配层
真实项目中块名极不稳定，不能只靠 `block_name` 识别语义。

```json
{
  "block_adapter_result": {
    "insert_id": "INS-001",
    "semantic_category_candidates": ["door"],
    "subtype_candidates": ["single_swing"],
    "basis": {
      "block_name": "DOOR_SINGLE",
      "attributes": {"MARK": "D03"},
      "layer": "A-DOOR"
    },
    "confidence": 0.82
  }
}
```

---

## 15. XREF 如何进入 JSON

### 15.1 为什么必须考虑 XREF
真实施工图中，很多信息通过外部参照进入：

- 结构底图
- 建筑底图
- 设备底图
- 公共底图

如果系统忽略 XREF：

- 有些墙 / 柱 / 门洞关系会缺失
- 结构柱位置可能拿不到
- 平面与其他专业关系会不完整

### 15.2 XREF 结构建议

```json
{
  "xref_id": "XREF-001",
  "name": "structural_base",
  "source_path": "../base/structural.dwg",
  "status": "resolved_or_unresolved",
  "attach_type": "attach",
  "transform": {
    "translation": [0,0],
    "rotation_deg": 0,
    "scale": [1,1,1]
  },
  "bound_document_id": "DOC-STR-001"
}
```

### 15.3 即使暂时不深解析，也要记录缺失

```json
{
  "xref_id": "XREF-001",
  "status": "missing",
  "impact": ["structural_column_rules_may_be_degraded"]
}
```

---

## 16. 推荐的核心语义对象清单

### 16.1 空间类
- Space
- Zone
- WetArea
- CirculationArea

### 16.2 建筑 / 装饰构件类
- Wall
- Door
- Window
- Column（可选）
- CeilingZone
- FloorFinishZone
- Skirting
- ThresholdStone

### 16.3 设备 / 灯具类
- Lighting
- Switch
- Socket
- DrainMark
- AirDiffuser（可选）
- SprinklerHead（可选）

### 16.4 标注与索引类
- LevelMark
- DetailCallout
- ElevationCallout
- SectionCallout
- MaterialTag
- DoorTag
- FinishTag

### 16.5 表类
- DrawingIndex
- DoorSchedule
- FinishSchedule
- ConstructionMethodTable

### 16.6 湿区专项类
- WaterproofZone
- DepressedSlab
- SlopeMark
- DrainMark

---

## 17. Space（房间/空间）对象设计

### 17.1 Space 是跨图锚点
很多跨图关系最终都要挂到 `space`：

- 平面中的房间
- 天花中的吊顶区
- 地坪中的地面分区
- 立面中的墙面
- 节点中的适用部位

### 17.2 Space 结构建议

```json
{
  "space_id": "SP-001",
  "name": "主卧",
  "aliases": ["Master Bedroom"],
  "boundary": {
    "coordinate_space": "canonical_review",
    "polygon": [[0,0],[5000,0],[5000,4200],[0,4200]]
  },
  "center": [2500,2100],
  "area_m2": 21.0,
  "floor_or_level": "L1",
  "related_logical_sheet_ids": ["LS-101", "LS-201", "LS-301"],
  "source_entity_ids": ["E-101", "E-102"],
  "confidence": 0.9
}
```

### 17.3 边界提取不准时的策略
允许：

- rough_bbox
- rough_polygon
- name_only_space
- 降低 confidence

POC 阶段宁可给粗糙空间，也不要因为追求完美而完全不产出空间对象。

---

## 18. Door / Wall / CeilingZone / FloorFinishZone 示例

### Door

```json
{
  "element_id": "D-03",
  "category": "door",
  "subtype": "single_swing",
  "position": [1200,3400],
  "rotation_deg": 90,
  "width_mm": 800,
  "height_mm": 2100,
  "mark": "D03",
  "from_space_id": "SP-005",
  "to_space_id": "SP-006",
  "host_wall_id": "W-11",
  "source_entity_ids": ["INS-001"],
  "confidence": 0.88
}
```

### Wall

```json
{
  "element_id": "W-11",
  "category": "wall",
  "axis": [[0,0],[3000,0]],
  "thickness_mm": 100,
  "wall_type": "light_steel_partition",
  "source_entity_ids": ["E-001", "E-002"],
  "confidence": 0.83
}
```

### CeilingZone

```json
{
  "element_id": "CZ-01",
  "category": "ceiling_zone",
  "space_id": "SP-001",
  "polygon": [[...]],
  "elevation_mm": 2700,
  "ceiling_type": "CL-02",
  "has_access_panel": true,
  "source_entity_ids": ["E-301"],
  "confidence": 0.85
}
```

### FloorFinishZone

```json
{
  "element_id": "FZ-01",
  "category": "floor_finish_zone",
  "space_id": "SP-001",
  "polygon": [[...]],
  "finish_code": "FL-05",
  "pattern": "herringbone",
  "source_entity_ids": ["E-401"],
  "confidence": 0.84
}
```

---

## 19. 标高体系：LevelMark 必须单独建模

没有标高体系，就无法可靠判断：

- 完成面标高
- 吊顶标高
- 结构降板
- 净高链
- 地面跌级

### LevelMark 示例

```json
{
  "level_mark_id": "LV-001",
  "mark_type": "FFL",
  "display_text": "+0.000",
  "value_mm": 0,
  "space_id": "SP-001",
  "owner_review_view_id": "RV-001",
  "source_space": "paper_space",
  "source_entity_ids": ["E-701"],
  "confidence": 0.92
}
```

常见 `mark_type`：

- FFL
- FCL
- SFL
- CL
- local_drop
- threshold_level

---

## 20. 湿区专项对象设计

### WetArea

```json
{
  "wet_area_id": "WA-001",
  "space_id": "SP-005",
  "area_type": "bathroom",
  "polygon": [[...]],
  "source_entity_ids": ["E-801"],
  "confidence": 0.87
}
```

### WaterproofZone

```json
{
  "waterproof_zone_id": "WPZ-001",
  "space_id": "SP-005",
  "polygon": [[...]],
  "height_requirement_mm": 1800,
  "source_entity_ids": ["E-802"],
  "confidence": 0.79
}
```

### DepressedSlab

```json
{
  "depressed_slab_id": "DS-001",
  "space_id": "SP-005",
  "drop_mm": 30,
  "source_entity_ids": ["E-803"],
  "confidence": 0.74
}
```

### DrainMark

```json
{
  "drain_id": "DR-001",
  "space_id": "SP-005",
  "position": [1200,600],
  "drain_type": "floor_drain",
  "source_entity_ids": ["INS-701"],
  "confidence": 0.86
}
```

### SlopeMark

```json
{
  "slope_mark_id": "SL-001",
  "space_id": "SP-005",
  "display_text": "1%坡向地漏",
  "slope_percent": 1.0,
  "direction_hint": "towards_drain",
  "source_entity_ids": ["TXT-701"],
  "confidence": 0.77
}
```

---

## 21. 关系层：Reference / Mapping / Graph

AI 审图不是只看单个对象，而是看关系：

- 门和门表是否一致
- 节点索引是否指向正确详图
- 立面是否对应某面墙
- 灯位是否在吊顶区域内
- 地漏是否在湿区内

### Reference 示例

```json
{
  "ref_id": "REF-001",
  "type": "detail_callout",
  "source_object_id": "W-21",
  "target_object_id": "DT-07",
  "source_logical_sheet_id": "LS-101",
  "target_logical_sheet_id": "LS-601",
  "label": "3/A-601",
  "confidence": 0.96,
  "basis": ["text_match", "spatial_nearby"]
}
```

常见关系类型：

- `detail_callout`
- `elevation_callout`
- `section_callout`
- `same_space_alignment`
- `schedule_binding`
- `inside`
- `hosted_by`
- `geometric_alignment`
- `level_alignment`
- `conflicts_with`

---

## 23. 推荐的顶层 JSON 结构

```json
{
  "project": {},
  "documents": [],
  "pages": [],
  "layouts": [],
  "layers": [],
  "block_definitions": [],
  "raw_entities": [],
  "normalized_entities": [],
  "transforms": [],
  "review_views": [],
  "logical_sheets": [],
  "spaces": [],
  "elements": [],
  "tables": [],
  "references": [],
  "dimension_evidence": [],
  "text_evidence": [],
  "issues": []
}
```

工程上也可以拆成多个 JSON：

- `raw_cad.json`
- `layouts_and_views.json`
- `semantic_objects.json`
- `evidence.json`
- `graph.json`

---

## 34. 一页总结（可直接放到项目文档首页）

**DWG->JSON 的正确做法，不是导出一份“图元列表 JSON”，而是构建一套分层审图中间表示：**

- Raw 层保留原始 CAD 对象
- Normalized 层统一字段和坐标
- Semantic 层表达房间、门、吊顶、地坪、节点、表格等审图对象
- Evidence 层表达尺寸真值、冲突状态和证据链

并且必须显式支持：

- model space / paper space
- viewport / review view / logical sheet
- 显示值 / 测量值 / 几何值三轨并存
- XREF / block / table / layer 的保留与映射

这样，JSON 才不是“导出结果”，而是整个 AI 审图系统的数据底座。

---

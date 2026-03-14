
# DWG→JSON Extensions（扩展专题）


> 版本：v1.2  
> 来源：基于 `DWG_TO_JSON_SPEC_v1.2.md` 重组  
> 目的：把“核心规范 / 扩展专题 / 实现说明 / LLM 消费说明”分层，便于开发团队、Codex、Claude Code 分阶段执行。  
>
> 规范级别说明：
> - **MUST**：当前系统必须满足
> - **SHOULD**：强烈建议满足，可在后续迭代补齐
> - **MAY**：可选扩展，不应阻塞当前里程碑


本文件收纳 **高价值但不一定属于当前最小实现子集** 的专题。它们大多值得保留，但不应在没有优先级控制的情况下全部压进当前迭代。

## 阅读建议

- 当前在做单项目 POC：先读 Core + Implementation Notes，本文件按需查阅。
- 当前在做项目级、多 DWG、复杂立面、清洗与公司适配：本文件为主。
## 35. 补充：多 DWG 文件的项目级关联机制

### 35.1 问题背景

原规范的设计范围主要是单个 DWG 文件内部的结构。但真实室内施工图项目通常由多个文件构成：

- `平面布置图.dwg`
- `天花图.dwg`
- `地坪图.dwg`
- `节点详图.dwg`
- 共 5–20 个文件

跨文件的语义关联（如"平面图的主卧 ↔ 天花图的主卧吊顶区"）需要一个**项目级锚点层**，否则 Reference 和 same_space_alignment 将缺乏权威依据。

### 35.2 DrawingRegister（图纸目录）必须单独建模

图纸目录本身就是一张图，是跨文档关联的 ground truth，应作为一级对象：

```json
{
  "project_id": "PROJ-001",
  "project_name": "XX 样板房精装修施工图",
  "drawing_register": {
    "source_document_id": "DOC-000",
    "source_table_id": "TB-INDEX-01",
    "entries": [
      {
        "sheet_number": "A-101",
        "title": "平面布置图",
        "document_id": "DOC-001",
        "logical_sheet_id": "LS-001",
        "floor_or_level": "L1",
        "sheet_type": "floor_plan"
      },
      {
        "sheet_number": "A-201",
        "title": "天花图",
        "document_id": "DOC-002",
        "logical_sheet_id": "LS-010",
        "floor_or_level": "L1",
        "sheet_type": "ceiling_plan"
      },
      {
        "sheet_number": "A-301",
        "title": "地坪图",
        "document_id": "DOC-003",
        "logical_sheet_id": "LS-020",
        "floor_or_level": "L1",
        "sheet_type": "floor_finish_plan"
      }
    ],
    "confidence": 0.91
  }
}
```

### 35.3 Project 层顶层结构

顶层 JSON 应增加：

```json
{
  "project": {
    "project_id": "PROJ-001",
    "project_name": "...",
    "floor_levels": ["B1", "L1", "L2"],
    "drawing_register_id": "DR-001",
    "document_ids": ["DOC-001", "DOC-002", "DOC-003"]
  },
  "drawing_register": {},
  "documents": [],
  ...
}
```

### 35.4 跨文件 Space 对齐策略

同一空间在多个文件中都会出现，需要明确对齐方式：

```json
{
  "space_id": "SP-001",
  "name": "主卧",
  "cross_document_refs": [
    { "document_id": "DOC-001", "logical_sheet_id": "LS-001", "local_space_id": "SP-DOC1-001", "sheet_type": "floor_plan" },
    { "document_id": "DOC-002", "logical_sheet_id": "LS-010", "local_space_id": "SP-DOC2-001", "sheet_type": "ceiling_plan" },
    { "document_id": "DOC-003", "logical_sheet_id": "LS-020", "local_space_id": "SP-DOC3-001", "sheet_type": "floor_finish_plan" }
  ],
  "alignment_basis": ["name_match", "geometric_overlap"],
  "confidence": 0.88
}
```

对齐方式优先级：
1. 空间名称完全匹配
2. 几何边界重叠（需坐标系对齐后计算）
3. 图纸目录中的图纸类型推断

---

## 36. 补充：块语义字典与 Block Attribute 的审图地位

### 36.1 问题背景

原规范的块对象（BlockDefinition / Insert）停留在几何和属性层面。但室内图中，块的 ATTRIB 是**审图数据的一等数据源**，而非附属文字：

| 块类型 | 关键 ATTRIB | 审图用途 |
|---|---|---|
| 门窗块 | MARK / WIDTH / HEIGHT / FIRE_RATING | 门表核验 |
| 节点索引块 | 图号 / 详图编号 | 索引指向验证 |
| 图框块 | 项目名 / 出图日期 / 版本号 | 版本一致性 |
| 洁具块 | TYPE / MODEL | 湿区完整性 |
| 灯具块 | TYPE / CIRCUIT | 回路对应 |

### 36.2 BlockSemanticProfile 对象

每个在项目中使用的 block，应生成一份语义档案：

```json
{
  "block_semantic_profile_id": "BSP-001",
  "block_name": "DOOR_SINGLE",
  "inferred_type": "door",
  "subtype_candidates": ["single_swing"],
  "key_attributes": [
    { "attr_name": "MARK",        "role": "door_mark",    "required": true  },
    { "attr_name": "WIDTH",       "role": "door_width",   "required": true  },
    { "attr_name": "HEIGHT",      "role": "door_height",  "required": true  },
    { "attr_name": "FIRE_RATING", "role": "fire_rating",  "required": false }
  ],
  "basis": {
    "block_name_pattern": "DOOR",
    "layer_pattern": "A-DOOR",
    "geometry_hint": "arc_quarter_circle"
  },
  "confidence": 0.92,
  "instance_count": 14
}
```

### 36.3 ATTRIB 必须进入 Insert 记录

当前规范的 Insert 结构已有 `attributes` 字段，但需明确每个属性的语义角色：

```json
{
  "insert_id": "INS-001",
  "block_name": "DOOR_SINGLE",
  "attributes": {
    "MARK":        { "raw_value": "D03", "semantic_role": "door_mark" },
    "WIDTH":       { "raw_value": "800", "numeric_value": 800, "unit": "mm", "semantic_role": "door_width" },
    "HEIGHT":      { "raw_value": "2100", "numeric_value": 2100, "unit": "mm", "semantic_role": "door_height" },
    "FIRE_RATING": { "raw_value": "乙级", "semantic_role": "fire_rating" }
  },
  "block_semantic_profile_id": "BSP-001"
}
```

### 36.4 块名不稳定的兼容策略

真实项目块名极不统一（`DOOR_SINGLE` / `M1` / `门-单扇` / `D-01-STD`），识别策略优先级：

1. 块名关键字匹配（`DOOR` / `门` / `M`）
2. 图层归属（`A-DOOR`）
3. 几何特征（圆弧 + 直线 = 门扇）
4. ATTRIB 字段名识别
5. 降级为 `unknown_insert`，保留 stub

---

## 37. 补充：净高计算链（ClearHeightChain）

### 37.1 问题背景

室内审图最高频的问题是**净高不足**。但净高是一条计算链，不是单个标注。原规范有 LevelMark，但没有显式建模这条推理路径，导致 LLM 需要自行从多个孤立标注反推，置信度低、容易出错。

### 37.2 净高链的构成

```
结构板底标高（SFL 或来自结构 XREF）
  ↓
机电管线占用区间（可选，来自机电图）
  ↓
吊顶完成面标高（FCL）
  ↓
地面完成面标高（FFL）
  ↓
净高 = FCL - FFL
```

### 37.3 ClearHeightChain 对象

```json
{
  "clear_height_chain_id": "CHC-001",
  "space_id": "SP-001",
  "space_name": "主卧",
  "FFL_mm": 0,
  "FFL_evidence_id": "LV-001",
  "FCL_mm": 2600,
  "FCL_evidence_id": "LV-002",
  "SFL_mm": 3200,
  "SFL_evidence_id": "LV-003",
  "plenum_height_mm": 600,
  "computed_clear_height_mm": 2600,
  "required_min_mm": 2400,
  "status": "pass",
  "conflict_note": null,
  "confidence": 0.87
}
```

`status` 枚举：
- `pass`：净高满足要求
- `fail`：净高不足
- `warning`：净高偏低，接近下限
- `unknown`：标高数据不完整，无法计算

### 37.4 常见净高审查规则依赖此对象

- 居住空间净高 ≥ 2400mm（《住宅设计规范》）
- 厨卫净高 ≥ 2200mm
- 走廊净高 ≥ 2200mm
- 局部降低区域不得超过室内面积 1/3

没有 ClearHeightChain，以上规则无法系统性执行。

---

## 38. 补充：立面图语义对象

### 38.1 问题背景

原规范有 `ElevationCallout`（平面图上的立面索引符号），但缺少**立面图本身的语义层**。立面图是室内施工图的核心图纸类型之一，包含大量不可替代的审图信息。

### 38.2 ElevationView 对象

```json
{
  "elevation_view_id": "EV-001",
  "logical_sheet_id": "LS-401",
  "review_view_id": "RV-041",
  "target_space_id": "SP-001",
  "facing_direction": "north",
  "wall_axis": [[0,0],[5000,0]],
  "callout_ref_id": "REF-EL-001",
  "confidence": 0.85
}
```

### 38.3 ElevationZone（立面材料分区）

类比 `CeilingZone` / `FloorFinishZone`，立面需要材料分区对象：

```json
{
  "elevation_zone_id": "EZ-001",
  "elevation_view_id": "EV-001",
  "zone_type": "wall_finish",
  "bbox_in_elevation": [0, 0, 2400, 1200],
  "finish_code": "WF-03",
  "material_description": "哑光涂料",
  "source_entity_ids": ["E-901"],
  "confidence": 0.80
}
```

### 38.4 ElevationElement（立面构件）

立面图中的门洞、窗洞、踢脚线、腰线、收口等：

```json
{
  "elevation_element_id": "EE-001",
  "elevation_view_id": "EV-001",
  "element_type": "door_opening",
  "bbox_in_elevation": [1200, 0, 2000, 2100],
  "width_mm": 800,
  "height_mm": 2100,
  "linked_door_id": "D-03",
  "source_entity_ids": ["E-902"],
  "confidence": 0.83
}
```

常见 `element_type`：
- `door_opening`
- `window_opening`
- `skirting`
- `dado_rail`
- `cornice`
- `niche`
- `panel_joint`

### 38.5 立面与平面的关联校验

立面图提供以下校验能力，需要依赖跨对象关联：

| 校验项 | 平面数据 | 立面数据 |
|---|---|---|
| 门洞净宽一致性 | Door.width_mm | ElevationElement.width_mm |
| 门洞净高一致性 | Door.height_mm | ElevationElement.height_mm |
| 材料对应 | FinishSchedule | ElevationZone.finish_code |
| 踢脚线连续性 | Wall 路径 | ElevationElement[skirting] |

---

## 39. 补充：图层状态组合（LayerState 快照）

### 39.1 问题背景

原规范中每个 Layer 有 `is_frozen / is_off` 字段，但这描述的是**当前全局状态**，不是每个 Layout 对应的可见性状态。

很多事务所使用"一套 model space + 多个图层状态"出不同图纸：

- 平面图：打开 `A-FURN / A-WALL / A-DOOR`，关闭 `A-CLNG / A-FLOR`
- 天花图：打开 `A-CLNG / A-LITE`，关闭 `A-FURN`
- 地坪图：打开 `A-FLOR / A-PATT`，关闭 `A-FURN / A-CLNG`

如果不捕获每个 Layout 对应的 LayerState 快照，语义提取时会混入其他图纸的图元，产生错误对象。

### 39.2 LayerState 快照结构

```json
{
  "layer_state_id": "LST-001",
  "owner_layout_id": "LAYOUT-01",
  "name": "CEILING_PLAN_STATE",
  "layer_visibility": [
    { "layer_name": "A-CLNG",  "visible": true  },
    { "layer_name": "A-LITE",  "visible": true  },
    { "layer_name": "A-FURN",  "visible": false },
    { "layer_name": "A-WALL",  "visible": true  },
    { "layer_name": "A-FLOR",  "visible": false }
  ],
  "source": "layout_embedded_state",
  "confidence": 0.95
}
```

`source` 枚举：
- `layout_embedded_state`：Layout 内嵌的图层状态（最可靠）
- `viewport_overrides`：Viewport 级图层覆盖
- `inferred_from_entity_visibility`：从可见 entity 反推（降级方案）

### 39.3 Viewport 级图层覆盖

部分 CAD 文件在 Viewport 层面单独控制图层可见性，优先级高于 Layout 全局状态：

```json
{
  "viewport_id": "VP-01",
  "owner_layout_id": "LAYOUT-01",
  "layer_overrides": [
    { "layer_name": "A-FURN", "visible": false, "override_type": "vp_freeze" }
  ]
}
```

### 39.4 对语义提取的影响

在语义提取阶段，必须先查询当前 ReviewView 对应的有效图层可见性，只处理可见图层的 entity：

```python
def get_visible_layers(review_view_id) -> set[str]:
    layout_id = get_layout_for_review_view(review_view_id)
    viewport_id = get_viewport_for_review_view(review_view_id)
    # viewport overrides 优先于 layout state
    base_state = get_layer_state(layout_id)
    vp_overrides = get_viewport_layer_overrides(viewport_id)
    return apply_overrides(base_state, vp_overrides)
```

---

## 40. 补充：Issue 输出格式规范

### 40.1 问题背景

原规范顶层 JSON 有 `"issues": []`，但没有定义 Issue 的字段结构。Issue 是整个 AI 审图系统最终的产品输出，必须从一开始就设计清楚，否则后续规则引擎和 LLM 的输出无法归一化。

### 40.2 Issue 对象完整结构

```json
{
  "issue_id": "ISS-001",
  "rule_id": "R-WET-003",
  "rule_name": "卫生间门净宽核验",
  "category": "dimension_conflict",
  "severity": "error",
  "title": "卫生间门净宽不足",
  "description": "卫生间 D-05 门净宽为 750mm，低于规范要求的 800mm。",
  "suggested_fix": "建议将门宽调整为 ≥ 800mm，或核实是否有特殊设计依据。",
  "evidence": {
    "primary_object_id": "D-05",
    "primary_object_type": "door",
    "measured_value": 750,
    "required_value": 800,
    "unit": "mm",
    "dimension_evidence_id": "DIM-012",
    "source_space": "model_space",
    "is_override": false,
    "supporting_object_ids": ["SP-005", "W-11"]
  },
  "location": {
    "logical_sheet_id": "LS-003",
    "logical_sheet_title": "卫生间平面图",
    "review_view_id": "RV-007",
    "document_id": "DOC-001",
    "bbox_canonical": [1200, 800, 1350, 1100],
    "center_canonical": [1275, 950]
  },
  "cross_sheet_refs": [
    {
      "logical_sheet_id": "LS-401",
      "role": "elevation_view",
      "note": "立面图 A-401 中门洞高度与此相关"
    }
  ],
  "confidence": 0.91,
  "generated_by": "rule_engine",
  "reviewed_status": "open"
}
```

### 40.3 字段说明

| 字段 | 说明 |
|---|---|
| `rule_id` | 触发此 Issue 的规则编号，可追溯到规则库 |
| `severity` | `error` / `warning` / `info` |
| `category` | 见 40.4 |
| `evidence` | 完整证据链，必须可追溯到原始 entity |
| `location.bbox_canonical` | 在 ReviewView canonical 坐标中的位置，用于前端高亮 |
| `cross_sheet_refs` | 涉及多张图纸时的跨图关联 |
| `generated_by` | `rule_engine` / `llm` / `hybrid` |
| `reviewed_status` | `open` / `accepted` / `rejected` / `fixed` |

### 40.4 Issue 分类（category）枚举

- `dimension_conflict`：尺寸冲突（标注与几何、图纸之间）
- `clearance_violation`：净高 / 净宽不足
- `missing_element`：缺少必要构件（如湿区无地漏）
- `schedule_mismatch`：图元与门表/材料表不一致
- `reference_broken`：节点索引指向不存在的详图
- `level_conflict`：标高矛盾
- `waterproof_incomplete`：防水构造不完整
- `cross_sheet_inconsistency`：跨图纸信息矛盾
- `annotation_missing`：缺少必要标注
- `code_violation`：违反规范条文

---

## 42. 补充：几何脏数据清洗层（Geometry Sanitization Layer）

### 42.1 问题背景

原规范提到 polygon/boundary，但真实 CAD 图纸普遍存在"几何噪声"，若不清洗，后续的语义提取和规则计算将产生大量误判：

- **不闭合墙线**：间隙 0.1mm–5mm，导致房间边界无法闭合
- **重叠线（Z-fighting）**：同位置多条线叠加，干扰墙厚识别
- **微短线**：长度 < 0.01mm 的碎线，破坏多边形拓扑
- **远坐标对象**：对象坐标在 (1e9, 1e9) 量级之外，导致浮点精度丢失

### 42.2 清洗层在流水线中的位置

```
Raw CAD JSON
    ↓
[几何清洗层]  ← 新增，位于 Raw → Normalized 之间
    ↓
Normalized CAD JSON
```

### 42.3 SanitizationLog 结构

```json
{
  "sanitization_log": {
    "entity_id": "E-001",
    "original_geometry_hash": "sha256:...",
    "cleaning_operations": [
      {
        "op": "extend_to_meet",
        "target_entity_id": "E-002",
        "gap_closed_mm": 0.5
      },
      {
        "op": "remove_duplicate_vertices",
        "removed_count": 3
      },
      {
        "op": "snap_to_grid",
        "grid_size_mm": 0.01
      },
      {
        "op": "remove_micro_segment",
        "segment_length_mm": 0.003
      }
    ],
    "validity_score": 0.94,
    "geometry_modified": true
  }
}
```

### 42.4 清洗操作枚举

| 操作 | 触发条件 | 说明 |
|---|---|---|
| `extend_to_meet` | 端点间距 < 容差阈值 | 延伸两线至相交 |
| `snap_to_grid` | 坐标精度过高 | 吸附到网格，消除浮点噪声 |
| `remove_duplicate_vertices` | 多边形中连续重复点 | 合并重复顶点 |
| `remove_micro_segment` | 线段长度 < 最小阈值 | 删除碎线 |
| `remove_overlap` | 两线完全重叠 | 保留一条，记录来源 |
| `reproject_far_object` | 坐标超出合理范围 | 重新投影或标记为孤立对象 |

### 42.5 浮点精度硬约束

**所有几何计算必须使用 64 位双精度浮点数（float64）。**

CAD 坐标常达 1e8 量级，32 位单精度浮点在此量级下精度约为 16mm，完全无法满足室内施工图 1mm 级审图需求。

### 42.6 清洗失败的降级处理

若清洗后对象仍无效（如自相交多边形无法修复），进入降级路径：

```json
{
  "entity_id": "E-099",
  "sanitization_status": "failed",
  "failure_reason": "self_intersecting_polygon_unresolvable",
  "fallback": "raw_geometry_preserved",
  "impacted_semantic_extraction": ["space_boundary", "wall_identification"]
}
```

---

## 43. 补充：动态块（Dynamic Blocks）有效几何提取

### 43.1 问题背景

室内图中门、窗、家具大量使用动态块（如可拉伸宽度的门、可翻转的洁具）。ezdxf 等库默认只能拿到块的**定义几何**，无法获取插入时的动态参数（如拉伸距离、翻转状态、可见性状态）。

如果只使用定义几何，门宽将始终等于块定义时的默认值，与实际设计意图不符。

### 43.2 DynamicBlock 解析结构

```json
{
  "insert_id": "INS-001",
  "block_name": "DOOR_DYNAMIC",
  "is_dynamic_block": true,
  "dynamic_params": {
    "width_stretch_mm": 900,
    "flip_horizontal": true,
    "flip_vertical": false,
    "visibility_state": "open_90deg",
    "lookup_value": "900mm"
  },
  "effective_geometry": {
    "resolved": true,
    "lines": [ ... ],
    "arcs": [ ... ],
    "bbox": [0, 0, 900, 900]
  },
  "dynamic_resolution_source": "oda_sdk"
}
```

### 43.3 动态块解析能力对比

| 解析引擎 | 动态块支持 | 说明 |
|---|---|---|
| ezdxf | ❌ 仅定义几何 | 开源，免费，动态参数不可靠 |
| ODA Platform | ✅ 完整支持 | 商业授权，推荐生产环境 |
| RealDWG | ✅ 完整支持 | Autodesk 官方，授权成本高 |

### 43.4 降级必须显式标记

若解析引擎无法提取动态参数，**禁止静默使用定义几何**，必须显式标记：

```json
{
  "insert_id": "INS-001",
  "is_dynamic_block": true,
  "effective_geometry": {
    "resolved": false,
    "degraded_reason": "dynamic_block_not_resolved",
    "fallback_geometry": "block_definition_default",
    "impacted_attributes": ["width_mm", "rotation_effective"]
  }
}
```

此标记将传播到上层语义对象：

```json
{
  "element_id": "D-03",
  "category": "door",
  "width_mm": 800,
  "width_confidence": 0.45,
  "width_degraded_reason": "dynamic_block_not_resolved_using_definition_default"
}
```

---

## 44. 补充：Viewport 异形裁剪（Clip Boundary）处理

### 44.1 问题背景

布局中的视口可能设置了**异形裁剪边界**（以 LWPOLYLINE 作为裁剪框），只显示模型空间的一部分。若忽略此点，裁剪框外的几何会被误认为是图纸内容，导致幽灵几何进入语义提取。

### 44.2 Viewport 裁剪结构

```json
{
  "viewport_id": "VP-01",
  "owner_layout_id": "LAYOUT-01",
  "standard_bbox": [100, 100, 600, 450],
  "clip_boundary": {
    "enabled": true,
    "clip_type": "polygonal",
    "boundary_polygon": [
      [120, 110], [580, 110], [580, 430], [120, 430], [120, 110]
    ],
    "source_entity_id": "E-CLB-01"
  },
  "effective_model_region": {
    "polygon_in_model_space": [ ... ],
    "bbox_in_model_space": [0, 0, 12000, 8000]
  }
}
```

### 44.3 对语义提取的影响

在语义提取阶段，必须先用裁剪边界过滤 entity，只处理落在有效区域内的对象：

```python
def get_visible_entities_in_viewport(viewport_id, all_entities):
    vp = get_viewport(viewport_id)
    clip_poly = vp.clip_boundary.boundary_polygon  # 转换到 model space
    return [
        e for e in all_entities
        if geometry_intersects(e.bbox, clip_poly)
    ]
```

`clip_type` 枚举：
- `rectangular`：标准矩形视口（默认）
- `polygonal`：任意多边形裁剪
- `none`：无裁剪

---

## 45. 补充：文字编码与字体 Fallback 策略

### 45.1 问题背景

CAD 文件常使用 Big5 / GB2312 / GBK / GB18030 / 自定义 SHX 字体，解析时频繁出现：
- 中文变问号（`??`）
- 中文变乱码（`¿¿`）
- SHX 字体无法渲染，文字完全丢失

文字丢失是室内施工图审图的致命伤：房间名、材料编号、图号、标高值全部依赖文字。

### 45.2 TextEntity 编码结构

```json
{
  "text_entity": {
    "source_entity_id": "E-201",
    "raw_bytes_hex": "D6F7CED4",
    "encoding_detected": "GB18030",
    "encoding_confidence": 0.97,
    "text_utf8": "主卧",
    "font_name": "simhei.shx",
    "font_substitution": "Noto Sans CJK SC",
    "font_substitution_reason": "shx_not_renderable",
    "ocr_fallback": null,
    "ocr_triggered": false
  }
}
```

### 45.3 编码解析策略（优先级顺序）

1. **DXF 文件头声明的编码**（最可靠）
2. **chardet / charset-normalizer 自动检测**
3. **按常见 CAD 编码顺序尝试**：GB18030 → GBK → Big5 → UTF-8
4. **OCR fallback**：将文字区域渲染为图片，用 OCR 识别（仅在前三步均失败时触发）

### 45.4 OCR Fallback 结构

```json
{
  "ocr_fallback": {
    "triggered": true,
    "trigger_reason": "encoding_all_failed",
    "ocr_engine": "paddleocr",
    "ocr_result": "主卧",
    "ocr_confidence": 0.89,
    "render_image_ref": "ocr_cache/E-201.png"
  }
}
```

### 45.5 字体 SHX 处理说明

SHX 是 AutoCAD 专有字体格式，开源库无法直接渲染。推荐策略：
- 维护常用 SHX → TTF 映射表（如 `hztxt.shx` → `Noto Sans CJK`）
- 标记字体替换，不影响文字内容提取
- 若字体替换导致字宽变化，不影响语义提取，但影响布局相关分析时需注意

---

## 46. 补充：Z 轴过滤与楼层高度分层

### 46.1 问题背景

平面图的 model space 中，不同高度的对象可能共存：
- 地面完成面（Z ≈ 0）
- 门窗洞口（Z = 0–2100）
- 梁底（Z = 2700–3200）
- 吊顶（Z = 2400–2700）
- 结构板（Z = 3000+）

若只取 XY 投影，梁、吊顶填充、高窗等对象会作为"幽灵几何"出现在平面图语义提取结果中，干扰房间边界识别和门窗识别。

### 46.2 Z-Range 过滤结构

在 Normalized 层增加 Z 轴信息：

```json
{
  "normalized_entity": {
    "entity_id": "E-301",
    "z_min": 0,
    "z_max": 2100,
    "z_range_label": "door_opening",
    "elevation_band": "human_accessible",
    "included_in_plan_extraction": true
  }
}
```

### 46.3 elevation_band 枚举

| 标签 | Z 范围（参考值） | 典型对象 |
|---|---|---|
| `floor_level` | Z = -100 ~ 50 | 地面填充、地坪线 |
| `human_accessible` | Z = 0 ~ 2400 | 墙、门、窗、家具 |
| `overhead` | Z = 2400 ~ 3000 | 高窗、梁底线、吊顶 |
| `structural` | Z > 3000 | 结构板、楼板 |

### 46.4 Z 轴信息缺失的降级处理

大量 CAD 对象 Z = 0（绘图者未设置高度），不能因此将其归为 `floor_level`。

降级策略：
- Z = 0 且图层为 `A-WALL` → 按 `human_accessible` 处理
- Z = 0 且图层未知 → 标记 `z_ambiguous: true`，不过滤，保留供 LLM 判断

---

## 48. 补充：公司解析 Profile（Company Parsing Profile）

### 48.1 问题背景

不同设计公司、设计院的绘图习惯差异极大：

- 有些爱在 Paper Space 标尺寸，有些在 Model Space 标
- 有些一个 Layout 一张图，有些一个 Layout 多张图
- 有些图层命名用英文标准，有些用中文拼音，有些随意命名
- 有些动态块大量使用，有些完全不用

这些差异不应硬编码（hard code）进解析逻辑，也不应用散落的 Feature Flag 控制（容易演变成难以维护的 if/else 迷宫）。

推荐使用**公司解析 Profile**：将每家公司的绘图习惯封装为一个可版本管理、可测试、可复用的配置对象。

### 48.2 CompanyParsingProfile 结构

```json
{
  "company_profile_id": "CP-001",
  "company_name": "某设计院",
  "version": "2024-01",
  "layer_naming": {
    "convention": "chinese_pinyin",
    "wall_patterns": ["QIANG", "WL", "墙体"],
    "door_patterns": ["MEN", "DR"],
    "ceiling_patterns": ["DINGBENG", "CEILING", "DB"]
  },
  "dimension_strategy": {
    "primary_source": "paper_space",
    "trust_override": true,
    "fallback": "model_space"
  },
  "layout_strategy": {
    "one_layout_multi_sheet": true,
    "title_block_detection": "heuristic"
  },
  "block_library": {
    "door_block_patterns": ["M-*", "门-*", "DOOR_*"],
    "node_ref_block_patterns": ["索引-*", "DETAIL_*"]
  },
  "encoding": {
    "preferred": "GB18030",
    "shx_font_map": {
      "hztxt.shx": "Noto Sans CJK SC",
      "gbcbig.shx": "Noto Sans CJK SC"
    }
  },
  "known_issues": [
    "frequently_draws_walls_on_layer_0",
    "uses_dynamic_blocks_for_all_doors"
  ],
  "created_from_samples": ["sample_A.dwg", "sample_B.dwg"],
  "confidence": 0.88
}
```

### 48.3 Profile 的生成与维护

- **初始**：手动配置，基于 5–10 套真实样本图纸分析
- **迭代**：每次解析失败 / 人工纠正后，自动更新 Profile 的匹配规则
- **版本管理**：Profile 本身纳入 Git，每次修改可追溯
- **复用**：同一设计院的不同项目共用同一 Profile

### 48.4 Profile 的应用点

解析流水线的以下节点读取 Profile：

| 流水线节点 | 读取 Profile 字段 |
|---|---|
| 图层分类器 | `layer_naming` |
| 块语义适配器 | `block_library` |
| 尺寸真值策略 | `dimension_strategy` |
| ReviewView 识别 | `layout_strategy` |
| 文字编码解析 | `encoding` |
| 几何清洗阈值 | `known_issues` |

---


# DWG→JSON Implementation Notes（实现说明）


> 版本：v1.2  
> 来源：基于 `DWG_TO_JSON_SPEC_v1.2.md` 重组  
> 目的：把“核心规范 / 扩展专题 / 实现说明 / LLM 消费说明”分层，便于开发团队、Codex、Claude Code 分阶段执行。  
>
> 规范级别说明：
> - **MUST**：当前系统必须满足
> - **SHOULD**：强烈建议满足，可在后续迭代补齐
> - **MAY**：可选扩展，不应阻塞当前里程碑


本文件关注 **如何实现与落地**，而不是重新定义对象模型。凡是会影响当前 Sprint 范围、后端选型、落库、测试、回归、降级的内容，都放在这里。

## 适用范围

- 面向单项目 POC、真实样板房项目、后续多项目扩展
- 适用于 `DWG + PDF + 可选 PNG` 混合输入
- 不要求一开始就完成所有高级专题（如完整动态块展开、异形 viewport 精确反投影）

## A. Schema Version 与兼容策略（新增）

**MUST** 在顶层 JSON 包中携带 schema 信息，例如：

```json
{
  "schema_name": "dwg_to_json_core",
  "schema_version": "1.2.0",
  "compatible_with": ["1.1.x"]
}
```

建议策略：

- 小版本新增字段时，保持向后兼容。
- 删除字段或变更字段语义时，必须提升 major 版本。
- 下游规则引擎与 LLM 消费层应首先检查 `schema_version`，再决定是否继续解析。

## B. ID 生成规范（新增）

建议同时维护两类 ID：

- `stable_id`：尽量与源路径、sheet number、entity handle、语义锚点绑定，便于多次解析保持一致。
- `runtime_id`：一次任务内唯一即可，便于流水线中间态组装。

**SHOULD** 保证：同一 DWG/页/实体在无实质变化的情况下，多次重跑得到相同的 `stable_id`。

## C. Tolerance Registry（新增）

几何清洗、闭合、对齐、去重都不应各自维护一套硬编码阈值。建议集中定义：

```json
{
  "tolerances": {
    "snap_grid_mm": 0.01,
    "gap_close_mm": 1.0,
    "micro_segment_mm": 0.1,
    "bbox_overlap_ratio": 0.6
  }
}
```

**MUST** 在回归测试中固定容差集，避免不同模块各写一套“差不多”的阈值。

## D. 解析能力矩阵（新增）

建议在实现文档或配置中维护能力矩阵，明确不同 backend 的上限，例如：

- ODA：DWG 原生对象、动态块、viewport、xref 支持较强
- ezdxf：基础几何与文本较强，复杂动态块和部分布局语义较弱
- PDF-only：页面级与标题级强，CAD 语义和几何证据弱

这不是运行时逻辑，而是交付与预期管理的一部分。

## 22. DWG -> JSON 推荐流水线

### Step 1: Document ingest
输入：DWG / 可选 DXF / 可选 PDF

### Step 2: Raw CAD extraction
输出：layouts / layers / blocks / raw entities / xrefs

### Step 3: Normalization
输出：normalized entities / transforms / unified ids

### Step 4: Layout / ReviewView analysis
输出：page -> review views / review view -> logical sheet candidates

### Step 5: Semantic extraction
输出：spaces / walls / doors / ceiling zones / floor zones / level marks / wet area chain / tables

### Step 6: Evidence extraction
输出：dimension evidence / text evidence / mapping evidence

### Step 7: Relationship graph build
输出：references / bindings / same-space alignments

### Step 8: Rule-ready JSON export
输出：semantic review json / evidence json / graph json

---

## 24. 推荐的落库策略

不要只存一个大 JSON 文件。建议同时支持：

### 24.1 文件落地
适合调试、回归测试、样本比对。

### 24.2 关系库存元数据
例如 PostgreSQL：

- documents
- pages
- layouts
- review_views
- logical_sheets
- spaces
- elements
- tables
- references
- issues

### 24.3 几何数据
POC 阶段可直接 JSON 化存储，后续再演进到更强几何存储。

---

## 25. 解析失败与降级策略

DWG->JSON 不可能第一次就 100% 完整，所以必须定义降级策略。

### 25.1 解析失败不等于信息丢失
如果对象无法完整展开，至少输出：

```json
{
  "entity_id": "E-999",
  "type": "UNRESOLVED_OBJECT",
  "reason": "unsupported_dynamic_block_variant",
  "raw_snapshot": {}
}
```

### 25.2 降级层次
- Level A：完整解析到语义对象
- Level B：只能解析到 normalized entity
- Level C：只能作为 raw entity 保留
- Level D：只能记录解析失败和影响范围

### 25.3 输出影响范围

```json
{
  "degradation_notice": {
    "id": "DG-001",
    "reason": "missing_xref",
    "impacted_rules": ["structural_column_clearance", "wall_alignment"],
    "severity": "medium"
  }
}
```

---

## 27. 兼容不同公司绘图习惯的要求

### 27.1 一布局一图
最简单：
- `1 layout ≈ 1 review view ≈ 1 logical sheet`

### 27.2 一布局多图
必须支持：
- `layout -> N review views`
- `review view -> logical sheet`

### 27.3 模型空间按图层管理，不同图纸共用一套底图
必须依赖：
- layer state
- page type
- review view
- paper space annotations

### 27.4 布局空间中存在关键标注
必须优先保留：
- paper_space text
- paper_space dimension
- title blocks
- tables

---

## 28. 常见错误设计（一定要避免）

### 28.1 只导出 entities
后果：无法审图、无法跨图、无法证据追溯。

### 28.2 只看 model space
后果：丢失标题、图号、纸空间尺寸、说明、表格。

### 28.3 把 layout 当成图纸
后果：一布局多图场景直接失真。

### 28.4 只保留显示值，不保留测量值
后果：无法发现标注与几何不一致。

### 28.5 语义对象不保留 source_entity_ids
后果：无法解释为什么识别为门/墙/湿区。

### 28.6 XREF 缺失时静默忽略
后果：系统误以为没有结构柱，而不是“数据不完整”。

### 28.7 一上来就只做一个巨大 JSON
后果：调试困难、版本 diff 困难、回归测试困难。

---

## 29. 推荐的最小可行输出（MVP）

如果先做最小版 DWG->JSON，建议最少输出：

### 必选
- document
- pages
- layouts
- layers
- raw_entities
- review_views
- logical_sheets
- spaces（哪怕粗糙）
- doors
- detail_callouts
- tables
- dimension_evidence
- references

### 可后补
- XREF 的深解析
- dynamic blocks 的高置信识别
- 精确 viewport transform
- 高复杂几何布尔计算

---

## 30. 推荐的回归测试清单

DWG->JSON 模块至少覆盖：

### 30.1 document / layout 层
- 能识别多个 layout
- 能识别 paper size
- 能处理 tab order

### 30.2 text / table 层
- 能提取 TEXT / MTEXT
- 能识别图号候选
- 能提取简单表格

### 30.3 review view 层
- 单布局单图
- 单布局多图
- 无 title block 的降级情况

### 30.4 dimension truth 层
- 无 override 的标准尺寸
- 有 override 的尺寸
- 布局空间尺寸
- 几何值与显示值冲突

### 30.5 xref 层
- XREF 可解析
- XREF 缺失
- 缺失时 impact 输出正确

---

## 31. 推荐的实现优先级

### 第一阶段
先做：
- Raw CAD JSON
- page / layout / review view
- text / title / drawing index
- dimension evidence

### 第二阶段
再做：
- spaces
- doors
- tables
- detail callouts
- references

### 第三阶段
再做：
- wet area chain
- level system
- construction methods
- xref-enhanced reasoning

### 第四阶段
再做：
- 更复杂的跨专业协调
- 更复杂的 geometry conflict
- 更多 project-type profiles

---

## 32. 给代码代理的硬约束

如果把这份文档交给 Codex / Claude Code，建议明确要求：

1. 不要把 DWG->JSON 简化为单层大字典
2. 必须区分 Raw / Normalized / Semantic / Evidence
3. 必须支持 model_space / paper_space
4. 必须支持 review_view / logical_sheet
5. 必须保留 source_entity_ids
6. 必须实现 dimension truth policy 的数据结构
7. XREF 即便不深解析，也要记录状态和影响范围
8. 允许启发式，但必须可解释、可追溯、可测试

---

## 33. 最终建议

对于你的项目，DWG->JSON 的正确定位不是：

> 把 DWG 换一种格式保存。

而是：

> 把 CAD 文档、布局、视口、纸空间标注、模型几何、审图语义对象、尺寸真值和证据链，统一转换成一套可供规则引擎与 LLM 使用的审图中间表示。

只有这样，后续这些事才会真正成立：

- 平面 / 天花 / 地坪 / 节点之间的关系理解
- 室内专项规则审查
- 设计意图与模型几何冲突检测
- 审图问题可追溯解释
- 与 Kimi / OpenRouter 等模型协同工作

---

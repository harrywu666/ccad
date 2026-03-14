
# DWG→JSON LLM Consumption Notes（LLM 消费说明）


> 版本：v1.2  
> 来源：基于 `DWG_TO_JSON_SPEC_v1.2.md` 重组  
> 目的：把“核心规范 / 扩展专题 / 实现说明 / LLM 消费说明”分层，便于开发团队、Codex、Claude Code 分阶段执行。  
>
> 规范级别说明：
> - **MUST**：当前系统必须满足
> - **SHOULD**：强烈建议满足，可在后续迭代补齐
> - **MAY**：可选扩展，不应阻塞当前里程碑


本文件只讨论 **上层 AI / LLM / Agent 如何消费 DWG→JSON 结果**。这不是 CAD 解析规范本身，而是“如何安全、稳定、可解释地把结构化结果交给模型”。

## 核心原则

1. **MUST NOT** 把 Raw CAD JSON 直接塞给 LLM 当主输入。
2. **MUST** 以 `Semantic + Evidence` 为主输入，以 `Normalized` 为辅助输入。
3. **MUST** 按 `ReviewView / LogicalSheet / Space / RuleScope` 做上下文切片。
4. **MUST** 对不确定、降级、缺失和冲突信息显式提示，不允许让模型隐式脑补。

## A. LLM 输入分层（新增）

推荐输入优先级：

1. `Semantic Review JSON`
2. `Evidence / Truth JSON`
3. 与当前问题直接相关的 `Normalized CAD JSON` 片段
4. 必要时补充页面截图、ReviewView 缩略图、表格截图

**禁止做法**：

- 一次性把整套 DWG 的 Raw entities 全量塞给模型
- 让模型自己推断 layout / page / viewport / sheet 的主关系
- 在没有证据链时要求模型“判断最终真值”

## B. 证据链传播规则（新增）

**SHOULD** 遵守以下原则：

> 任何 Semantic Object 的 `confidence` 不应高于其核心证据链中最低可信环节的上限。

例如：

- 文字来自 OCR fallback
- XREF 缺失
- 动态块仅部分展开
- geometry sanitization 失败后降级

这些情况都应把不确定性向上传播到高层对象，而不是只在局部打一个备注。

## C. 建议的 Context Slice 组成（新增摘要）

一个适合给 LLM 的切片通常包含：

- 当前 `ReviewView` 或 `LogicalSheet` 的元数据
- 当前规则范围内的 semantic objects
- 与其直接相连的 evidence objects
- 必要的 normalized 几何摘要
- 降级/缺失/冲突说明
- 最多一到几张相关截图，而不是整套图纸

## 5. 为什么不能直接把 DWG 底层对象导出成一个大 JSON 然后喂给 LLM

因为 Raw Entity JSON 只有“图元信息”，没有：

- 布局 / 视口层
- 逻辑图纸层
- 跨图锚点
- 标注真值策略
- 证据链
- 审图语义对象

例如下面这种 JSON：

```json
{
  "entities": [
    {"type": "LINE", "layer": "A-WALL", "start": [0,0], "end": [3000,0]},
    {"type": "INSERT", "block_name": "DOOR", "position": [500,0]},
    {"type": "TEXT", "text": "主卧", "position": [1200,600]}
  ]
}
```

LLM 当然“能看懂一点”，但很难稳定完成这些任务：

- 判断门和门表是否一致
- 判断一个 layout 里是不是有两张图
- 判断纸空间尺寸是否比模型几何更能代表设计意图
- 判断平面中的房间如何和天花/地坪/节点对应

所以 Raw JSON 只能作为中间层，不能直接充当审图输入。

---

## 26. AI 审图为什么必须保留证据链

最终 issue 不能只输出：

> 卫生间门净宽不足。

而应能回溯：

- 门对象来自哪个 insert
- 门宽来自哪条尺寸或哪个属性
- 该尺寸在模型空间还是布局空间
- 是否有 override
- 关联哪张图、哪个 review view
- 几何值是多少
- 设计意图值是多少

这要求 DWG->JSON 从一开始就保留：

- `source_entity_ids`
- `owner_review_view_id`
- `source_space`
- `truth_role`
- `confidence`
- `basis`

---

## 41. 补充：LLM 上下文切片策略

### 41.1 问题背景

原规范设计了完整的数据结构，但没有说明 **LLM 每次推理时应该拿哪些数据**。大型项目的完整 JSON 可能达到数百万字符，远超任何模型的 context window，且无关信息会严重干扰推理质量。

必须在数据层之上设计**上下文切片（Context Slice）策略**，让每次 LLM 调用的输入精准、完整、不超限。

### 41.2 切片单位：以 Space 为核心

审图的基本推理单元是**单个空间（Space）**。对一个 Space 的审图，需要汇聚以下信息：

```
Space 上下文切片 = {
  Space 基础信息（名称、面积、边界）
  + 所有关联 Door（含属性、门表对应行）
  + 所有关联 Wall（含类型、厚度）
  + CeilingZone（标高、类型、灯位）
  + FloorFinishZone（材料、节点引用）
  + LevelMark 列表（FFL / FCL / SFL）
  + ClearHeightChain
  + WetArea / WaterproofZone / DrainMark（如适用）
  + DetailCallout 列表 → 对应节点 Semantic 内容
  + ElevationCallout 列表 → 对应立面 ElevationView 摘要
  + 相关 DimensionEvidence
  + 适用规则文本
}
```

### 41.3 ContextSlice 对象

```json
{
  "context_slice_id": "CS-001",
  "slice_type": "space_review",
  "target_space_id": "SP-001",
  "target_space_name": "主卧",
  "applicable_rule_ids": ["R-CLR-001", "R-DIM-003", "R-FIN-002"],
  "token_estimate": 3200,
  "payload": {
    "space": { ... },
    "doors": [ ... ],
    "walls": [ ... ],
    "ceiling_zones": [ ... ],
    "floor_finish_zones": [ ... ],
    "level_marks": [ ... ],
    "clear_height_chain": { ... },
    "detail_callouts": [ ... ],
    "elevation_summaries": [ ... ],
    "dimension_evidence": [ ... ],
    "applicable_rules": [ ... ]
  }
}
```

### 41.4 其他切片类型

| 切片类型 | 适用场景 | 核心内容 |
|---|---|---|
| `space_review` | 单房间全面审查 | Space + 关联所有对象 |
| `door_schedule_check` | 门表核验 | DoorSchedule + 所有 Door |
| `finish_schedule_check` | 材料表核验 | FinishSchedule + 所有 FloorFinishZone / ElevationZone |
| `reference_check` | 节点索引完整性 | 所有 DetailCallout + 目标 LogicalSheet |
| `wet_area_chain` | 湿区专项 | WetArea + WaterproofZone + DrainMark + SlopeMark + DepressedSlab |
| `cross_sheet_alignment` | 跨图一致性 | 同一 Space 的平面/天花/地坪摘要 |
| `level_system_review` | 标高体系审查 | 所有 LevelMark + ClearHeightChain |

### 41.5 切片 Token 预算控制

每次 LLM 调用应控制在 token 预算内：

```python
MAX_SLICE_TOKENS = 8000  # 为 CoT 和输出预留余量

def build_context_slice(space_id, rule_ids):
    payload = {}
    budget = MAX_SLICE_TOKENS

    # 按优先级加入，超预算时降级
    for component, fetcher in COMPONENT_PRIORITY:
        data = fetcher(space_id)
        tokens = estimate_tokens(data)
        if tokens <= budget:
            payload[component] = data
            budget -= tokens
        else:
            payload[component] = truncate_or_summarize(data, budget)
            break

    return payload
```

组件优先级（从高到低）：
1. Space 基础信息
2. 适用规则文本
3. 关联 Door（含属性）
4. LevelMark + ClearHeightChain
5. CeilingZone / FloorFinishZone
6. DimensionEvidence
7. DetailCallout 内容（可摘要）
8. ElevationView 摘要

### 41.6 多轮推理策略

对于复杂空间，单次 context 不够时，采用**多轮策略**而非单次全量：

```
第一轮：空间结构审查（尺寸、净高、门宽）
  → 输出初步 Issue 列表

第二轮：材料与节点审查（finish_code → 节点内容）
  → 补充材料相关 Issue

第三轮：跨图一致性审查（平面 vs 天花 vs 立面）
  → 补充跨图冲突 Issue

汇总 → 去重 → 置信度加权 → 最终 Issue 列表
```

每一轮都是一个独立的 ContextSlice，结果通过 `space_id` 和 `rule_id` 归并。

---

---

## 47. 补充：语义歧义的处理边界

### 47.1 原则

> 不要试图在解析阶段解决所有歧义。保留歧义比强行给出低置信度的确定答案更有价值。

此原则正确，但需要明确**边界**：并非所有歧义都适合保留到 LLM 阶段。

### 47.2 必须在解析层解决的歧义（不可甩给 LLM）

| 歧义类型 | 原因 |
|---|---|
| 坐标系归属（model / paper space） | LLM 无法做坐标变换，必须在解析时确定 |
| 图层可见性 / Viewport 裁剪 | 决定哪些 entity 存在，必须在解析时过滤 |
| 尺寸 override 冲突（display vs measured） | 必须结构化为 DimensionEvidence，不能作为文字歧义保留 |
| 编码乱码 | 必须在文字提取层解决，LLM 看不到原始字节 |

### 47.3 可以保留给 LLM 判断的歧义

```json
{
  "element_id": "E-099",
  "ambiguous_classification": {
    "primary_candidate": {
      "type": "window",
      "confidence": 0.65,
      "basis": ["layer_A-WIND", "geometry_rectangle"]
    },
    "secondary_candidate": {
      "type": "glass_partition",
      "confidence": 0.35,
      "basis": ["thickness_100mm", "full_height_hint"]
    },
    "resolution_strategy": "llm_spatial_context"
  }
}
```

适合保留歧义的情形：
- 语义分类不确定（窗 vs 玻璃隔断）
- 设计意图不明（标注缺失、说明不清）
- 跨图关联置信度低（索引符号模糊）

### 47.4 歧义不等于信息丢失

保留歧义的正确姿势是**结构化保留**，而非丢弃：

- 提供 `primary_candidate` + `secondary_candidate`
- 提供 `basis`（判断依据）
- 提供 `resolution_strategy`（建议解决路径）
- 不得静默丢弃，不得强行选一个

---

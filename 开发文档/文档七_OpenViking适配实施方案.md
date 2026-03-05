# 文档七：OpenViking 适配实施方案（CAD 审图系统）
## 版本：V1.0 | 日期：2026-03-05

---

## 一、结论（先说最终方案）

不直接“接入 OpenViking 全套框架”，而是采用 **OpenViking 思路 + 你现有后端结构** 的轻量实现：

1. 引入 **L0/L1/L2 三层图纸上下文**（按图纸页组织，不改你当前上传流程）
2. 引入 **任务规划器（Planner）**：按“平面 -> 索引 -> 立面/节点”生成审核任务图
3. 引入 **并发执行器（Executor）**：单图语义与图对核对分层并发
4. 引入 **可观测检索/审核轨迹（Trace）**：前端可视化每条问题的来源链路
5. 保持你当前核心前提：
   - ODA + ezdxf
   - 5 图输入（全图150DPI + 象限300DPI）
   - Kimi 主审，不加规则兜底

这是当前“收益最大、改造风险最低”的最优解。

---

## 二、OpenViking 可借鉴点（与本项目映射）

### 2.1 架构分层可复用
- OpenViking 将流程拆成：检索、会话、解析、压缩、存储。
- 本项目映射：
  - 解析：PDF/DWG 提取
  - 检索：图纸任务定位（不是通用知识检索）
  - 会话：审核轮次上下文（项目级）
  - 存储：SQLite + 项目文件目录

### 2.2 L0/L1/L2 分层可直接迁移
- L0：超短摘要，适合快速定位候选图纸
- L1：结构化概览，适合图对任务判定
- L2：完整 JSON + 5 图图像，适合最终核对

### 2.3 “意图分析 -> 分层检索 -> 重排”可迁移为“任务规划 -> 图对召回 -> 排序执行”
- OpenViking 用 TypedQuery；本项目改为 TypedTask：
  - `index_check`
  - `dimension_check`
  - `material_check`

### 2.4 异步队列与并发执行模式可迁移
- OpenViking 的队列化语义处理思路，可用于你现在最慢的尺寸核对阶段。

### 2.5 可观测性（trace）值得迁移
- 每条审核问题附带“从哪个平面、通过哪个索引、落到哪个立面”的过程链。

---

## 三、适配后的目标架构（本项目）

```
上传目录/图纸PDF/DWG
    ↓
Ingestion（现有流程）
    ↓
Context Builder（新增）
  - 生成每张图的 L0/L1/L2
    ↓
Task Planner（新增）
  - 基于索引关系生成任务图 DAG
    ↓
Executor（增强）
  - Stage A: 单图语义并发
  - Stage B: 图对核对并发
    ↓
Result Merger（增强）
  - 去重、冲突归并、证据链落库
    ↓
前端可视化（后续）
  - 问题列表 + 路径轨迹 + 证据预览
```

---

## 四、数据模型改造（最小必要）

在不破坏现有 `projects/catalog/drawings/json_data/audit_results/audit_runs` 的前提下新增：

### 4.1 `sheet_contexts`
- `id`
- `project_id`
- `catalog_id`
- `sheet_no`
- `sheet_name`
- `layer_l0`（短摘要，约100 token）
- `layer_l1`（结构化概览，约1-2k token）
- `layer_l2_json_path`（指向 json_data 最新路径）
- `layer_l2_pdf_path`
- `layer_l2_page_index`
- `semantic_hash`（用于缓存失效）
- `updated_at`

### 4.2 `sheet_edges`
- `id`
- `project_id`
- `source_sheet_no`
- `target_sheet_no`
- `edge_type`（`index_ref`/`material_ref`/`layout_ref`）
- `confidence`
- `evidence_json`（索引号、坐标、block属性等）

### 4.3 `audit_tasks`
- `id`
- `project_id`
- `audit_version`
- `task_type`（index/dimension/material）
- `source_sheet_no`
- `target_sheet_no`
- `priority`
- `status`（pending/running/done/failed）
- `trace_json`
- `result_ref`

### 4.4 `audit_artifacts`（缓存与证据）
- `id`
- `project_id`
- `sheet_no`
- `artifact_type`（`image5`/`sheet_semantic`/`pair_compare`）
- `cache_key`
- `content_path_or_json`
- `created_at`

---

## 五、核心流程重写（按你当前代码目录）

### 5.1 Context Builder（新增服务）
新增：`cad-review-backend/services/context_service.py`

职责：
1. 从 `drawings + json_data + catalog` 生成每图 L0/L1/L2
2. 从 `indexes` 生成 `sheet_edges`
3. 计算 `semantic_hash`

### 5.2 Task Planner（新增服务）
新增：`cad-review-backend/services/task_planner_service.py`

规则：
1. 先找平面类图（A1.* 等 + 布局关键词）
2. 仅对“平面 -> 索引目标图”生成 dimension/material 任务
3. 同图对去重
4. 根据风险打分（跨专业、尺寸密集、历史高问题）决定优先级

### 5.3 Executor（增强现有 `audit_service.py`）
现有尺寸核对改成两阶段并发：

1. **单图语义阶段（SheetAgent）**
   - 输入：5图 + DWG尺寸数据
   - 输出：语义尺寸列表
   - 并发：`SHEET_AGENT_CONCURRENCY`（建议默认 8）

2. **图对核对阶段（PairAgent）**
   - 输入：两张图的语义尺寸列表
   - 输出：不一致问题列表
   - 并发：`PAIR_AGENT_CONCURRENCY`（建议默认 16）

3. **缓存策略**
   - `cache_key = sha256(project_id + sheet_no + pdf_mtime + json_hash + prompt_version)`
   - 命中即跳过 Kimi 调用

### 5.4 Trace（新增）
每条 `audit_results` 增加 `trace_json`（可先在 `description` 内嵌 JSON，再迁移字段）：
- planner 决策
- 任务执行耗时
- 使用的图片/数据版本
- Kimi 请求ID（若可得）

---

## 六、性能优化（重点回答“如何加快审核效率”）

### 6.1 必做（高收益）
1. 单图语义并发
2. 图对核对并发
3. 5图缓存
4. 单图语义缓存
5. 图对去重 + 任务剪枝

### 6.2 进阶（中收益）
1. 任务优先级调度（先高风险图对）
2. prompt 分片（尺寸太多时分批）
3. 失败重试与熔断（按图任务级）

### 6.3 预期收益（44页项目）
- 当前：尺寸阶段可能长时间串行阻塞
- 优化后目标：
  - 首轮：整体时间下降 40%~65%
  - 二轮重复审核（缓存命中）：下降 70%+

---

## 七、多 Agent 协同方案（重点回答“能否多 Agent 协同”）

推荐 3-Agent（不额外引入汇总/校验 LLM）：

1. `PlannerAgent`（可先算法实现，非LLM）
   - 生成审核任务 DAG

2. `SheetAgent`（Kimi）
   - 每图一次 5图输入，产出结构化语义

3. `PairAgent`（Kimi）
   - 图对一致性核对

汇总由**代码层**完成（你已明确偏好），不是再加 LLM 汇总。

---

## 八、与你现有代码的对应改造点

1. `services/audit_service.py`
   - 拆出 Planner/Sheet/Pair 三段
   - 加缓存与并发控制

2. `services/audit_runtime_service.py`
   - 进度细化到任务级（不是仅 20/55/85）
   - 支持失败任务重跑

3. `routers/audit.py`
   - 新增任务视图接口：`/audit/tasks`
   - 新增 trace 接口：`/audit/trace/{result_id}`

4. `models.py`
   - 新增 `sheet_contexts/sheet_edges/audit_tasks/audit_artifacts`

---

## 九、分阶段实施计划（建议）

### P1（2-3天）
- 落 `sheet_contexts` + `sheet_edges`
- 任务规划器（算法版）
- 不改前端

### P2（2-4天）
- 尺寸审核并发化
- 5图与语义缓存
- 任务级进度

### P3（2-3天）
- trace 落库与接口
- 前端可视化对接（后续）

---

## 十、验收标准（必须量化）

1. 功能正确性
- 三线 ready=44 时，任务总数稳定可复现
- 尺寸问题结果可追溯到具体图对与坐标证据

2. 性能
- 44页项目尺寸审核耗时显著下降（目标至少 40%）
- 二次审核缓存命中率 > 70%

3. 稳定性
- 单任务失败不拖垮整批任务
- 失败可重试，重试不重复写脏数据

---

## 十一、最终决策

**最优适配方案**：  
采用 OpenViking 的“分层上下文 + 任务规划 + 递归检索 + 并发执行 + 轨迹可观测”思想，  
但只在你当前 CAD 审图后端落地最小必要子集，避免引入完整 OpenViking 的工程复杂度。

这条路线能在最短时间内同时解决你最关心的两件事：
1. 审核效率（并发+缓存+剪枝）  
2. 多 Agent 协同（Planner + Sheet + Pair）


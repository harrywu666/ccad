# 旧版 Stage Prompt 收编进新架构 实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 把仍然直接挂在 `stage_key` 上的旧版 prompt，分阶段收编到新的 `Agent / Skill / 运行时模板` 架构里，最终让设置页主视角只保留 Agent 文件和 Skill 文件。

**架构：** 不搞“一次性搬家”。先按职责把旧 prompt 拆成 3 层：`AGENTS.md` 管硬边界，`SOUL.md` 管判断风格，`SKILL.md` 管能力说明；只有那种强依赖变量占位符、直接拼装上下文的部分，才留在运行时模板层。每迁完一块，就缩小一块旧版兼容层。

**技术栈：** FastAPI、Python、React、Vitest、pytest、现有 `agent_asset_service` / `worker_skill_loader` / `ai_prompt_service`

---

### 任务 1：给所有旧 stage 做去向清单

**文件：**
- 修改：`/Users/harry/@dev/ccad/docs/plans/2026-03-11-chief-review-worker-swarm-implementation-plan.md`
- 修改：`/Users/harry/@dev/ccad/docs/plans/2026-03-11-review-worker-skillization-implementation-plan.md`
- 创建：`/Users/harry/@dev/ccad/docs/plans/2026-03-12-stage-prompt-mapping.md`

**要做什么：**
- 把每个现存 `stage_key` 列出来。
- 明确它最后应该归到哪一层：
  - `AGENTS.md`
  - `SOUL.md`
  - `SKILL.md`
  - 运行时模板
- 明确哪些已经部分收编，哪些还完全没动。

**当前建议映射：**
- `master_task_planner` → `chief_review/AGENTS.md` + `chief_review/SOUL.md` + 一个独立的主审运行时模板
- `sheet_relationship_discovery` → `review_worker` 关系类 skill + 关系运行时模板
- `index_visual_review` → `index_reference/SKILL.md` + 局部复核模板
- `material_consistency_review` → `material_semantic_consistency/SKILL.md` + 局部复核模板
- `dimension_single_sheet` / `dimension_visual_only` / `dimension_pair_compare` → 尺寸类 skill + 视觉/对比模板
- `catalog_recognition` / `sheet_recognition` / `sheet_summarization` / `sheet_catalog_validation` → 图纸识别 Agent，后面单独建一个识别 Agent 目录

### 任务 2：把“规则说明”和“模板文本”彻底分开

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/ai_prompt_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/agent_asset_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/worker_skill_loader.py`

**要做什么：**
- 从旧 prompt 里把不带变量的规则说明抽出来。
- 能放到 `AGENTS.md / SOUL.md / SKILL.md` 的，先迁走。
- `{{sheet_no}}`、`{{payload_json}}` 这种强模板内容，继续留在运行时模板层。

**验收口径：**
- 任一运行时模板文件里，不再混着大段“角色定义”和“风格要求”。
- 任一 `AGENTS.md / SOUL.md / SKILL.md` 里，不再塞进大段变量占位模板。

### 任务 3：先收最成熟的 3 条链路

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/agents/review_worker/skills/index_reference/SKILL.md`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/agents/review_worker/skills/material_semantic_consistency/SKILL.md`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/agents/review_worker/skills/dimension_consistency/SKILL.md`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/review_worker_runtime.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/ai_prompt_service.py`

**要做什么：**
- 第一批只收：
  - `index_visual_review`
  - `material_consistency_review`
  - `dimension_*`
- 每收完一条，就把旧 stage 里的“说明性内容”削掉，只留下运行时模板骨架。

**为什么先做这 3 条：**
- 已经有原生 worker / skill 化基础。
- 风险比识别链路和总控链路低。
- 收一条就能立刻验证新设置页里的 skill 文件是不是更有意义。

### 任务 4：给主审单独补“主审模板层”

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/agents/chief_review/templates/`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/agents/chief_review/AGENTS.md`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/agents/chief_review/SOUL.md`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/chief_review_session.py`

**要做什么：**
- 不再让 `master_task_planner` 承担“主审人格 + 主审模板”两种职责。
- 主审自己的边界和风格都回到 `chief_review` 目录。
- 真正要拼变量的 JSON 任务模板，单独放到 `templates/`。

### 任务 5：识别链路独立成“识别 Agent”

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/agents/drawing_recognition/AGENTS.md`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/agents/drawing_recognition/SOUL.md`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/agents/drawing_recognition/MEMORY.md`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/agents/drawing_recognition/templates/`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/ai_prompt_service.py`

**要做什么：**
- 把 4 个识别相关 stage 从“提示词表”里抽成独立 Agent。
- 识别链路后面也走 Agent 资源读取，不再只是 prompt stage 表。

### 任务 6：前端兼容层逐步收缩

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/settings/SettingsLegacyStagePrompts.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/settings/SettingsPrompts.tsx`

**要做什么：**
- 每迁完一类 stage，就从兼容层主列表里去掉。
- 兼容层里只保留“还没收编”的项。
- 当兼容层只剩 1-2 个孤儿阶段时，再评估是否彻底删除。

### 任务 7：设置和运行时打一一追踪

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/finding_synthesizer.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/review_task_schema.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/worker_skill_contract.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/types/api.ts`

**要做什么：**
- 每条结果里能看出来到底吃的是：
  - 哪个 Agent 文件版本
  - 哪个 Skill 文件版本
  - 哪个运行时模板版本
- 后面出误报或回归时，能定位到是“Agent 改坏了”还是“模板改坏了”。

### 任务 8：删除旧版 stage 设置前的最终门槛

**前置条件：**
- 所有仍在执行链路里的旧 stage，都已经有明确新归属。
- 设置页兼容层为空，或只剩纯内部模板且用户无需直接改。
- `test1` 这种真实项目对比能稳定跑出至少一轮结果。
- 运行日志能追到 Agent / Skill / 模板版本。

**只有满足这些条件，才允许做：**
- 下线 `/api/settings/ai-prompts`
- 删除 `AIPromptSetting` 配置入口
- 删除前端“旧版阶段设置（兼容层）”

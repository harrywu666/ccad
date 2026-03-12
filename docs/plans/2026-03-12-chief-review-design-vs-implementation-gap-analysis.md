# 主审群审图设计与当前实现偏差清单

## 目的

这份清单只做一件事：把以下两份文档里的目标，和当前仓库里的真实实现逐项对齐，判断哪里已经做到，哪里只做到一半，哪里还没开始。

- `/Users/harry/@dev/ccad/docs/plans/2026-03-11-chief-review-worker-swarm-implementation-plan.md`
- `/Users/harry/@dev/ccad/docs/plans/2026-03-11-review-worker-skillization-implementation-plan.md`

结论先说：

- 当前系统已经不是老流程直跑了，`chief_review` 主路、主审会话、副审池、worker skill 骨架都已经接上。
- 但它还不是文档里那种“主审真正统领、副审真正 skill 驱动、旧 stage prompt 退居兼容层”的最终形态。
- 更准确的状态是：`新骨架已落地，旧脑子还没完全退场`。

---

## 一、整体判断

### 1. 已达成

- 已有 `chief_review` 主路，默认分流也已经切过去。
- 已有 `ChiefReviewSession / ReviewWorkerPool / WorkerTaskCard / WorkerResultCard` 这套运行时骨架。
- 已有 5 个 worker 的 `SKILL.md` 资源。
- 已有 `worker_skill_registry`，5 个 worker 都能走 skill 注册入口。
- 已有 `sheet graph / project memory / cross-sheet locator / evidence prefetch` 这些新架构基础件。

### 2. 半达成

- 主审已经能生成怀疑卡并派副审，但怀疑卡主要还是规则拼出来的，不是真正由主审资源驱动。
- worker skill 已经接进运行时，但很多 skill 还在复用旧专项实现，不是彻底独立的“新副审脑子”。
- 旧 `stage prompt` 已经被标记成兼容层，但运行时还在大量实际消费它们。

### 3. 未达成

- `AGENTS.md / SOUL.md / MEMORY.md` 还没有真正成为主审和副审的第一决策来源。
- 旧 `master_task_planner + stage prompt + 专项 audit` 还没有真正退出业务中心。
- 事件、步骤、运行状态的语言体系还明显偏旧，所以从日志到前端都还像老系统。

---

## 二、按设计目标逐项对照

## 1. 设计目标：业务决策中心从旧总控切到主审

### 文档期望

- 业务决策中心应该是 `chief_review_agent + worker dispatcher + sheet graph + project memory`
- 主审负责理解项目、生成怀疑卡、派副审、汇总结论、处理冲突

### 当前实现

- 已有 `chief_review` 主路，分流点在：
  - `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 已有主审会话：
  - `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/chief_review_session.py`
- 已有主审汇总：
  - `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/finding_synthesizer.py`

### 偏差

- 主审现在更像“规则路由器”，不是“真正的主审脑”。
- 怀疑卡主要由 `_build_default_hypotheses(...)` 根据 `sheet_graph.linked_targets + target_type` 生成。
- `ChiefReviewSession.plan_worker_tasks()` 也主要是把已有 hypothesis 转成 task，不是在做真正的审图判断。

### 判断

- `骨架已达成`
- `主审决策能力半达成`

### 下一步

- 让主审真正吃自己的 `AGENTS.md / SOUL.md / MEMORY.md`
- 把“怀疑卡生成”从规则拼装升级成“主审资源驱动 + memory 约束”

---

## 2. 设计目标：`AGENTS.md / SOUL.md / MEMORY.md` 成为主资源

### 文档期望

- Agent 资源才是角色行为的主来源
- Prompt 只负责运行时变量拼装，不再承担角色定义

### 当前实现

- 已有资源目录和加载器：
  - `/Users/harry/@dev/ccad/cad-review-backend/services/agent_asset_service.py`
- 前端也已经能编辑这些资源文件。

### 偏差

- 资源“存在”，不等于资源“接管了运行时”。
- 当前很多实际调用还在吃 `ai_prompt_service.py` 里的旧 `stage prompt`。
- `chief_review` 资源虽然已接到 prompt assembler，但主审怀疑卡生成本身仍主要靠规则，不靠资源。

### 判断

- `资源加载已达成`
- `资源接管运行时半达成`

### 下一步

- 先把主审资源接管主审规划
- 再把副审 skill 的系统提示完全改成 `review_worker + SKILL.md`
- 让旧 stage prompt 只剩用户提示模板和变量填充

---

## 3. 设计目标：副审能力 skill 化

### 文档期望

- `review worker runtime` 只做调度
- skill 负责领域规则、证据偏好、输出约束、升级条件
- 第一阶段先做 `index_reference` 和 `material_semantic_consistency`

### 当前实现

- 已有 skill 合同与加载层：
  - `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/worker_skill_loader.py`
  - `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/worker_skill_contract.py`
  - `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/worker_skill_registry.py`
- 当前已注册的 5 个 worker：
  - `index_reference`
  - `material_semantic_consistency`
  - `node_host_binding`
  - `elevation_consistency`
  - `spatial_consistency`

### 偏差

- `index_reference / material_semantic_consistency` 已经比较接近“真正的 worker skill”
- 但 `node_host_binding / elevation_consistency / spatial_consistency` 还明显复用旧链路
- `review_worker_runtime.py` 里仍保留内建分支，这说明 runtime 还没有完全退成纯调度层

### 判断

- `skill 外壳已达成`
- `skill 真正接管领域逻辑半达成`

### 下一步

- 优先继续把 `dimension / relationship` 从旧实现抽薄
- 最终目标是：`review_worker_runtime.py` 只负责找 executor，不再关心领域细节

---

## 4. 设计目标：旧 stage prompt 退居组装层

### 文档期望

- `PROMPT` 退居组装层
- JSON 与代码只做候选整理、缓存、调度、校验、恢复

### 当前实现

- `ai_prompt_service.py` 里已经给旧阶段加了：
  - `lifecycle=legacy_template_compat`
  - `replacement=...`
- 设置页里也已经把它们收到“旧版阶段设置（兼容层）”

### 偏差

- “被标记成兼容层”和“真的只剩兼容作用”是两回事。
- 当前这些旧阶段仍在真实驱动审图：
  - `master_task_planner`
  - `index_visual_review`
  - `dimension_single_sheet`
  - `dimension_pair_compare`
  - `material_consistency_review`
  - `sheet_relationship_discovery`

### 判断

- `命名和分层意图已达成`
- `运行时权重下沉未达成`

### 下一步

- 按领域逐个迁走旧 stage prompt 的“角色定义”
- 最后只留下：
  - 用户任务模板
  - 变量占位
  - 极少量兼容逻辑

---

## 5. 设计目标：旧专项 Agent 不再是主链核心

### 文档期望

- 旧“总控 + 关系/尺寸/材料 Agent”的流水线应退出中心
- 新系统应以主审和 worker 群为中心

### 当前实现

- 入口已经走主审主路
- 但运行现场仍然主要表现为：
  - `尺寸审查Agent`
  - `关系审查Agent`
  - `dimension_sheet_semantic`
  - `dimension_pair_compare`

### 偏差

- 从业务心智看，当前真实工作仍然明显沿着旧专项拆法在推进。
- 尤其尺寸链路，仍然是：
  - 单图语义
  - 双图比对
  - 问题合成  
 这还是旧尺寸审查逻辑的延续，只是被包进了 `chief_review` 外层。

### 判断

- `入口已切`
- `内部工作流未完全切`

### 下一步

- 保留旧专项代码做底层工具没问题
- 但要逐步去掉“旧专项就是业务主脑”的痕迹
- 包括：
  - 事件名
  - 步骤名
  - 状态口径
  - 运行时组织方式

---

## 6. 设计目标：主审 + 副审群 + LLM-first 跨图定位/证据服务

### 文档期望

- 主审决定查什么
- 副审群按任务卡查
- 跨图定位和证据服务成为自然基础设施

### 当前实现

- `cross_sheet_locator / evidence_prefetch / evidence_service / hot_sheet_registry` 已经在仓库里
- 主审也会产出任务卡，副审也确实是按 task 在跑

### 偏差

- 这些新服务已经存在，但还没彻底成为“所有副审天然第一入口”
- 尺寸链目前最明显还是自己那套“单图语义 + pair compare”拆法
- 证据服务参与了，但主审任务心智还没完全统一成“群审图网络”

### 判断

- `基础设施已达成`
- `业务工作流统一半达成`

### 下一步

- 先别推翻现有尺寸链
- 但要逐步把“证据包 / anchor / pair evidence”统一成 worker skill 的标准输入

---

## 三、为什么你会强烈感觉“还是不一样”

原因不在某一个 bug，而在下面 4 个地方同时存在：

- 主路虽然切了，但主审还不够像“真正的主审”
- skill 虽然有了，但很多只是新外壳包旧逻辑
- 旧 stage prompt 虽然降级了名字，但运行时还在重度使用
- 事件、步骤、状态语言还是老系统口径

所以你看到真实 run 时，体感当然会是：

- 看起来进了新架构
- 但闻起来、跑起来、报进度的样子还是老系统

这个感觉是对的，不是错觉。

---

## 四、当前完成度判断

按“文档原意”来估，不按“代码量”来估：

- 新骨架：`80%+`
- 新资源接管：`50% 左右`
- 旧链路退出：`30% 左右`

一句话总结：

- `架子搭起来了`
- `脑子换了一半`
- `旧系统还没退场`

---

## 五、接下来最该做的 3 件事

### 1. 先让主审真的成为主审脑

- 不再主要依赖 `_build_default_hypotheses(...)`
- 让 `chief_review` 资源真正驱动：
  - 怀疑卡生成
  - 冲突复核
  - memory 学习

### 2. 再让 skill 真正接管旧 stage prompt

- 优先顺序建议：
  - `index_reference`
  - `material_semantic_consistency`
  - `node_host_binding`
  - `dimension / elevation / spatial`

### 3. 最后统一运行现场语言

- 把事件、步骤、状态从旧专项口径收成：
  - 主审
  - 副审任务卡
  - skill
  - 收束/复核  
- 不然就算底层变了，产品观感也还是老系统

---

## 六、可直接拿去排期的偏差优先级

### P0：必须先做

- 主审资源真正接管怀疑卡生成
- `dimension / relationship` 从旧 prompt 驱动继续抽薄

### P1：很快要做

- 旧 `stage prompt` 从“兼容层名义”变成“兼容层现实”
- `review_worker_runtime.py` 继续瘦身，只保留调度职责

### P2：后续收口

- 统一事件语言
- 统一步骤状态
- 统一前端等待态心智模型

---

## 七、最终判断

如果只问一句：

`现在的审图流程和文档设计是不是还有差距？`

答案是：

`是，而且差距主要不在入口，而在真正驱动审图行为的那层还没完全换掉。`

如果再追问一句：

`是不是方向错了？`

答案是：

`不是方向错了，而是现在处在新旧切换的中段，骨架先换了，决策层和语言层还没彻底换完。`

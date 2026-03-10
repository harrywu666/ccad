# 尺寸审查 Agent 向 Runner 汇报 设计稿

**目标：** 让尺寸审查 Agent 在遇到拿不准、输出不稳、原地打转时，先向 Runner 汇报现场情况，由 Runner 先自救、协调、收口，最后再把整轮结果统一整理给用户。

**一句大白话：** 尺寸审查 Agent 不再一慌就“上报人工”，而是先把困难讲清楚，交给 Runner 这个中层管理者处理。

---

## 1. 现在的问题

当前链路里，尺寸审查 Agent 更像“直接产出问题清单的员工”：

- 它主要输出 `AuditResult`
- 置信度低、轮次高时，容易落到 `needs_review`
- 一旦输出格式反复不稳，运行层和内容层容易混在一起

这就会带来两个坏结果：

1. 员工自己跑不稳，会被翻译成“需要人工介入”
2. 用户过早看到半成品结论，误以为整轮审图真的结束了

这和目标不一致。目标应该是：

- 中途以 Runner 播报为主
- 中途异常先内部消化
- 整轮跑完后再统一汇报

---

## 2. 设计原则

这次只改尺寸审查 Agent，不同时改索引和材料。

原则如下：

- 主流程骨架不推翻
- Runner 继续做项目级观察和管理
- 尺寸审查 Agent 继续负责查尺寸
- 但尺寸审查 Agent 不能再只交“问题结果”
- 它必须同时交“工作汇报”

一句大白话：

`员工继续干活，但每次都要给主管写日报。`

---

## 3. 推荐方案

### 方案 A：工作汇报制（推荐）

尺寸审查 Agent 每次完成一小批工作时，除了现有问题列表，还要补一份结构化汇报：

- 已确认的问题
- 还没拿稳的问题
- 当前阻塞
- 希望 Runner 提供的帮助
- 自己对本批结果的把握程度

Runner 收到后：

- 能自己消化就消化
- 能重试就重试
- 能补证据就补证据
- 不能解决的，先记账，不中断整轮

优点：

- 最符合“Runner 是中层管理者”
- 最适合后面复制到索引和材料
- 能把“运行异常”和“内容异常”拆开

缺点：

- 要新增一层汇报结构
- 要给 Runner 加一层内部收件逻辑

### 方案 B：只改 prompt

只让尺寸审查 Agent 少说 `needs_review`，多说“继续观察”。

优点：

- 改得快

缺点：

- 太脆
- 治标不治本
- 一旦换现场，很容易又偏回去

### 方案 C：让 Runner 事后再读结果兜底

尺寸 Agent 还是照旧产出，等跑完后 Runner 再统一清洗。

优点：

- 对现有调用点改动小

缺点：

- 中途还是会出现坏状态
- 不能及时自救

**结论：选方案 A。**

---

## 4. 新的数据流

新的尺寸阶段，拆成两条输出：

### 4.1 结果输出

还是现有那套：

- `confirmed` 问题
- `suspected` 问题
- 最终写入 `AuditResult`

### 4.2 汇报输出

新增一份给 Runner 的结构化汇报，暂定叫 `DimensionAgentReport`：

- `batch_summary`
- `confirmed_findings`
- `suspected_findings`
- `blocking_issues`
- `runner_help_request`
- `agent_confidence`
- `next_recommended_action`

一句大白话：

`问题清单是交付物，工作汇报是内部管理信息。`

---

## 5. Runner 怎么接这个汇报

Runner 不直接把这份汇报端给用户，而是先内部处理。

### 5.1 Runner 内部判断

当尺寸 Agent 报上来以下情况时，Runner 优先自己接手：

- 同类输出连续不稳
- 同一批次反复重跑
- 证据不够完整
- 某组图纸反复打转
- Agent 自己明确请求帮助

### 5.2 Runner 可做的动作

只允许安全动作：

- `broadcast_update`
- `restart_subsession`
- `rerun_current_batch`
- `request_more_evidence`
- `defer_batch_and_continue`

这里故意不放：

- 中途 `mark_needs_review`
- 中途中断整轮
- 直接把半成品结论暴露给用户

---

## 6. 用户看到什么

用户默认只看到 Runner 的播报，不看尺寸 Agent 的内部汇报。

例如：

- “尺寸审查正在核对第 3 批尺寸关系”
- “这一批结果有点不稳，Runner 正在重新整理”
- “刚才这组图纸卡了一下，Runner 已自动重启当前子会话”
- “尺寸审查已继续推进，稍后统一汇总问题”

用户不该直接看到：

- “review_round=3”
- “needs_secondary_review”
- “raw validation failed”

一句大白话：

`员工怎么汇报是内部沟通，用户只听主管播报。`

---

## 7. 状态语义怎么改

当前最大的问题之一，是把“跑不稳”翻译成“人工介入”。

这次要把状态拆开：

- 内容结论：
  - `confirmed`
  - `suspected`
- 运行状态：
  - `stable`
  - `unstable`
  - `blocked`
  - `recovered`
  - `deferred`

也就是：

- 内容有没有问题，是一回事
- 这名员工现在跑得稳不稳，是另一回事

不要再混成一个 `needs_review`。

---

## 8. 代码层怎么改

只先动尺寸链路相关文件。

### 8.1 新增

- `cad-review-backend/services/audit_runtime/agent_reports.py`
  - 放尺寸 Agent 的统一汇报结构

### 8.2 修改

- `cad-review-backend/services/audit/dimension_audit.py`
  - 让尺寸 Agent 额外产出汇报
- `cad-review-backend/services/audit_runtime/agent_runner.py`
  - 接收并记录尺寸 Agent 汇报
- `cad-review-backend/services/audit_runtime/state_transitions.py`
  - 把汇报桥接成内部事件
- `cad-review-backend/services/audit_runtime/runner_observer_feed.py`
  - 让 Observer 也能看到“员工汇报”
- `cad-review-backend/services/audit_runtime/runner_broadcasts.py`
  - 把内部汇报翻成人话播报

---

## 9. 事件设计

新增两类内部事件：

- `agent_status_reported`
  - 员工交日报
- `runner_help_requested`
  - 员工明确向 Runner 求助

可能新增一类恢复事件：

- `runner_help_resolved`
  - Runner 接手后问题已恢复

注意：

- 这些事件默认属于内部层
- 前端默认不直接展示原始内容
- 前端继续展示翻译后的 `runner_broadcast`

---

## 10. 测试策略

先从测试倒推实现。

至少要补这些测试：

1. 尺寸 Agent 输出汇报结构
2. 输出不稳时，不再直接升成中途人工介入
3. Runner 收到求助后会选安全动作
4. 用户默认只看到 Runner 播报，不看到内部汇报原文
5. 整轮跑完后，最终问题汇总仍然正确

---

## 11. 风险

### 风险 1：事件太多

如果每一小步都汇报，会让事件流太吵。

处理方式：

- 只在批次结束、异常升级、请求帮助时汇报

### 风险 2：Runner 过度干预

如果 Runner 每次都插手，主流程会变慢。

处理方式：

- 先让尺寸 Agent 自己完成一轮
- 满足“连续不稳 / 明确求助 / 原地打转”才升级给 Runner

### 风险 3：前端又把内部状态当最终状态

处理方式：

- 内部汇报和最终报告严格分层
- 只把 `runner_broadcast` 暴露给默认前端流

---

## 12. 成功标准

做到下面这几条，就算第一版成功：

- 尺寸 Agent 中途不再把运行波动误报成人工介入
- 尺寸 Agent 遇到卡点时，能先向 Runner 求助
- Runner 能处理一部分尺寸阶段的波动
- 用户中途只看到 Runner 播报
- 最终报告只在整轮结束后统一整理

---

## 13. 这版先不做什么

第一版刻意不做：

- 不同步改索引 Agent
- 不同步改材料 Agent
- 不重做整个 orchestrator
- 不改数据库大表结构
- 不引入新的外部依赖

一句话总结：

`先把一个员工带稳，再复制经验给其他员工。`

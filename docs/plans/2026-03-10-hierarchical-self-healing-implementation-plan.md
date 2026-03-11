# 分层自救审图架构实现计划

> **给 Codex：** 这份计划用于按批次推进“员工 -> 总控 -> Runner -> 守护层”的分层自救能力。要求严格按小步验证推进：每一批都先补失败测试，再实现，再跑最小回归。

**目标**

把审图系统升级成一套分层自救体系：

- 子 Agent 出问题，由总控带记忆重启
- 总控出问题或开始瞎指挥，由 Runner 带记忆重启
- Runner 出问题，由守护层纯代码拉起

**边界**

- 不改项目工作区权限边界
- 不引入新依赖
- 不做大范围重构
- 优先补恢复链和记忆链，不先做花哨 UI

---

## 总体节奏

按 4 批推进：

1. **批次 1**
   先把“总控持续在线 + 任务账本 + 子 Agent 局部失败不拖死整轮”做实

2. **批次 2**
   再做“总控带记忆重启子 Agent”

3. **批次 3**
   再做“Runner 识别总控挂掉 / 瞎指挥，并带记忆重启总控”

4. **批次 4**
   最后做“守护层盯 Runner 心跳和快照，纯代码拉起 Runner”

---

## 批次 1：先把总控从“派工员”改成“持续带班经理”

### 目标

- 总控不再派完工就结束
- 总控能持续读取任务表和子 Agent 日报
- 尺寸 / 关系 / 索引 / 材料里单个任务炸掉时，整轮不直接失败

### 做什么

1. 在总控循环里加入持续带班逻辑
2. 明确任务账本是唯一真相源
3. 子 Agent 的局部异常只影响对应任务，不直接抛成整轮异常
4. 总控要能读当前任务状态并决定继续推进

### 重点文件

- `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py`
- `/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- `/Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py`
- `/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py`
- `/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`

### 先写失败测试

新增测试建议：

- `tests/test_orchestrator_task_resilience.py`
  - 子 Agent 单任务异常时，整轮仍维持 `running`
  - 失败任务只标记局部任务，不标整轮 `failed`

- `tests/test_orchestrator_continues_after_agent_failure.py`
  - 某个 Agent 的部分任务失败后，总控仍继续后续阶段

### 通过标准

- 单个子任务异常不再直接把 `AuditRun.status` 变成 `failed`
- 总控能继续推进后面的任务或阶段

---

## 批次 2：做“总控带记忆重启子 Agent”

### 目标

- 子 Agent 挂了，总控能用任务级记忆重启它
- 重启后继续当前任务，不是从零重开

### 做什么

1. 新增任务级恢复记忆结构
2. 总控收到 `agent_status_reported` 后，能判断是否需要重启子 Agent
3. 总控重启时把任务级记忆塞回去
4. 记录恢复账本：重启次数、最后原因、上次是否成功
5. 单任务重启次数超过上限后，不再无限重试；而是标记为 `permanently_failed`，写入内部日报，然后跳过继续推进整轮

### 新增文件建议

- `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/task_recovery_memory.py`
- `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/master_agent_recovery.py`

### 重点修改文件

- `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py`
- `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_reports.py`

### 先写失败测试

- `tests/test_master_agent_recovers_subagent.py`
  - 子 Agent 抛错后，总控触发带记忆重启
  - 恢复后从原任务继续

- `tests/test_task_recovery_memory.py`
  - 任务级记忆能保存和恢复当前批次上下文

### 通过标准

- 子 Agent 重启后仍保留当前任务上下文
- 重启次数可追踪
- 同一坏任务不会无限死循环重启
- 单任务重启次数超过上限后，会进入 `permanently_failed`，不会继续卡住整轮

---

## 批次 3：做“Runner 带记忆重启总控”

### 目标

- 总控挂了，Runner 能带项目级记忆把它拉起来
- 总控没挂但开始瞎指挥时，Runner 也能接管

### 做什么

1. 定义总控异常的 4 种触发：
   - 总控进程异常退出
   - 总控长时间无心跳
   - 总控失忆
   - 总控行为异常

2. 明确“总控行为异常”的判断规则
   - 连续 N 次重排同一批任务
   - 子 Agent 连续求助但总控不处理
   - 任务完成数长时间不增长
   - 调度动作明显不合理

3. `N` 的初始值建议设为 `3`，并定义在 `master_agent_health.py` 里作为常量，不要把这个数字硬编码在判断逻辑里
4. Runner 读取项目级记忆并重启总控
5. 重启后总控从任务账本继续跑

### 新增文件建议

- `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/master_agent_health.py`
- `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/project_recovery_memory.py`

### 重点修改文件

- `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_observer_session.py`
- `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_observer_feed.py`
- `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py`
- `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`

### 先写失败测试

- `tests/test_runner_recovers_master_agent.py`
  - 总控挂掉后，Runner 带记忆重启总控

- `tests/test_runner_detects_master_behavior_anomaly.py`
  - 总控连续重复重排任务时，Runner 主动接管

### 通过标准

- 总控挂掉不再直接等于整轮失败
- “没挂但瞎指挥”也能触发 Runner 介入
- “连续 3 次重排同一批任务”这类行为异常，能稳定触发 Runner 评估，而不是散落在多个地方各自猜一个阈值

---

## 批次 4：做“守护层纯代码拉起 Runner”

### 目标

- Runner 挂了，系统还能靠纯代码守护层恢复
- 守护层不接 AI，只看心跳和快照

### 做什么

1. 为 Runner 加轻量心跳
2. 为 Runner 加项目级快照存储
3. 新增守护层：
   - 监控 Runner 心跳
   - 监控 Runner 进程
   - 监控快照是否可恢复
4. Runner 无心跳或进程消失时，守护层拉起并恢复快照

### 新增文件建议

- `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_heartbeat.py`
- `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_snapshot_store.py`
- `/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_guardian.py`

### 先写失败测试

- `tests/test_runner_heartbeat.py`
  - 长操作期间仍会写心跳

- `tests/test_runner_guardian.py`
  - Runner 心跳超时后，守护层能拉起 Runner

- `tests/test_runner_snapshot_store.py`
  - Runner 快照可写可读可恢复

### 通过标准

- 守护层不会把“快照未更新”误判成“Runner 已挂”
- Runner 心跳和快照是分离的
- Runner 挂掉后能恢复项目级记忆
- 守护层拉起 Runner 后，Runner 能从最近快照恢复 `master_status_summary`，不是从空状态重新启动

---

## 数据结构建议

### 任务级记忆

建议字段：

- `task_id`
- `task_type`
- `source_sheet_no`
- `target_sheet_no`
- `current_batch_key`
- `last_error`
- `restart_count`
- `partial_outputs`
- `last_help_request`

### 项目级记忆

建议字段：

- `project_id`
- `audit_version`
- `current_stage`
- `task_summary`
- `recent_agent_reports`
- `recent_master_actions`
- `recent_runner_decisions`
- `risk_summary`

### 系统级快照

建议字段：

- `project_id`
- `audit_version`
- `runner_summary`
- `last_runner_action`
- `last_heartbeat_at`
- `snapshot_written_at`
- `master_status_summary`

---

## 状态和事件建议

为了后面更稳，建议补这些内部事件：

- `master_agent_heartbeat`
- `master_agent_restarted_subagent`
- `master_agent_requeued_task`
- `runner_restarted_master_agent`
- `runner_detected_master_anomaly`
- `runner_heartbeat`
- `runner_snapshot_written`
- `runner_guardian_restart`

这些事件默认只进内部运行总结，不进普通用户报告。

---

## 真实验收顺序

### 验收 1：子 Agent 局部故障

目标：

- 模拟尺寸 Agent 一个 worker 抛错
- 验证整轮仍继续
- 验证总控接手并重排

### 验收 2：总控挂掉

目标：

- 模拟总控异常退出
- 验证 Runner 接手并恢复总控

### 验收 3：总控瞎指挥

目标：

- 模拟总控反复重排同一批任务
- 验证 Runner 主动判定“行为异常”并接管

### 验收 4：Runner 挂掉

目标：

- 模拟 Runner 无心跳 / 进程消失
- 验证守护层能纯代码恢复 Runner

---

## 风险与控制

### 风险 1：恢复链太长，调试困难

控制：

- 每层只处理下一层
- 不做跨层直接救火

### 风险 2：无限重启

控制：

- 每层都要有最大恢复次数
- 超限后降级成“冻结局部任务 + 记录内部总结”

### 风险 3：把正常慢误判为挂掉

控制：

- 心跳和快照分离
- 长操作前必须先写心跳

### 风险 4：恢复后失忆

控制：

- 每次关键动作后落账本
- 以数据库账本为唯一真相源

---

## 推荐执行顺序

最推荐的顺序还是：

1. 先做“总控持续带班 + 局部失败不拖死整轮”
2. 再做“总控带记忆重启子 Agent”
3. 再做“Runner 带记忆重启总控”
4. 最后做“守护层拉起 Runner”

原因很简单：

- 先稳住最常见的小故障
- 再补中层恢复
- 最后补系统级兜底

这样每一批都能单独验收，不容易一锅端。

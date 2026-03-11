# Review Worker Skill 化第二阶段边界

## 第一阶段已完成

- `index_reference` 已拆成独立 worker skill
- `material_semantic_consistency` 已拆成独立 worker skill
- `review_worker_runtime` 已改成优先走 skill registry，再回退 builtin worker
- 主审任务卡和 findings 已能透传 `execution_mode / skill_id / skill_path`

## 第二阶段暂不做

- `node_host_binding`
- `elevation_consistency`
- `spatial_consistency`
- `chief_review / runner / observer / recovery / event bus` 系统骨架 skill 化

## 第二阶段风险

- `relationship` 依赖跨图 discovery，多轮证据与子会话恢复耦合更深
- `dimension` 依赖单图语义 + pair compare + provider 节流，拆 skill 时更容易把吞吐问题再放大
- 当前 `WorkerSkillBundle` 还没有 `skill_version`，日志追踪粒度还不够

## 第二阶段前置条件

- 真实项目 `test1` 在当前 skill 化后能稳定跑出一轮结果
- `WorkerSkillBundle` 补 `skill_version` 字段

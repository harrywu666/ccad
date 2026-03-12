# test1 上线前静态准备清单

## 当前结论

- 目标项目：`test1`
- 项目 ID：`proj_20260309231506_001af8d5`
- 当前代码状态：后端全量测试已通过
- 当前阻塞项：`kimi_sdk` 后台状态不稳定，所以这份清单只做静态准备，不启动真实 run

## 已有基线

- 老架构历史产物：
  - `/Users/harry/@dev/ccad/.artifacts/manual-checks/proj_20260309231506_001af8d5-ai-review-flow-check.json`
  - `/Users/harry/@dev/ccad/.artifacts/manual-checks/proj_20260309231506_001af8d5-http_127.0.0.1_7002-ai-review-flow-check.json`
- 旧的 `kimi_sdk` 验收产物：
  - `/Users/harry/@dev/ccad/.artifacts/manual-checks/proj_20260309231506_001af8d5-kimi_sdk-http_127.0.0.1_7002-codex-switch-check.json`

## 跑前前置检查

### 1. 后端代码健康

已经验证通过：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q
```

结果基线：

- `395 passed`

### 2. 运行方式固定

真实验收时只允许：

- `provider_mode = kimi_sdk`
- `AUDIT_CHIEF_REVIEW_ENABLED=1`

不要用：

- `codex_sdk`
- 未显式指定 `--provider-mode kimi_sdk` 的默认路径

### 3. 推荐的限流参数

目的是先稳，再看吞吐。

```bash
export AUDIT_RUNNER_PROVIDER=sdk
export AUDIT_CHIEF_REVIEW_ENABLED=1
export AUDIT_PROJECT_LLM_MAX_CONCURRENCY=1
export AUDIT_PROJECT_LLM_MIN_INTERVAL_SECONDS=0
export AUDIT_KIMI_SDK_MAX_CONCURRENCY=1
export AUDIT_KIMI_SDK_RATE_LIMIT_COOLDOWN_SECONDS=20
export AUDIT_KIMI_SDK_RATE_LIMIT_RETRY_LIMIT=8
export AUDIT_SDK_STREAM_IDLE_TIMEOUT_SECONDS=45
```

说明：

- 项目级总闸门默认已经偏保守，这里显式写死，避免环境漂移
- Kimi 官方并发上限你说是 `30`，但当前验收目标不是冲吞吐，是先把 `test1` 稳跑完一轮

## 真正启动时要用的命令

先只保留这一条，不要发散：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && \
AUDIT_RUNNER_PROVIDER=sdk \
AUDIT_CHIEF_REVIEW_ENABLED=1 \
AUDIT_PROJECT_LLM_MAX_CONCURRENCY=1 \
AUDIT_KIMI_SDK_MAX_CONCURRENCY=1 \
./venv/bin/python utils/manual_check_ai_review_flow.py \
  --project-id proj_20260309231506_001af8d5 \
  --base-url http://127.0.0.1:7002 \
  --start-audit \
  --provider-mode kimi_sdk
```

## 运行时观察点

重点只看这几类：

### 1. provider 是否真的对

看生成的报告 JSON 里：

- `checks.runtime_audit.runner_metrics.provider_mode`
- `checks.runtime_audit.runner_metrics.provider_names_seen`

必须看到：

- `provider_mode = kimi_sdk` 或 `sdk`
- 不应该混入 `codex_sdk`

### 2. 主审开关是否真的生效

看运行事件和结果：

- 是否出现 chief review 相关 worker task
- findings / escalations 是否带 `skill_id`
- `index_reference` / `material_semantic_consistency` 是否走 skill 元数据

### 3. 是否仍然被 Kimi 打爆

重点盯：

- `429`
- 长时间无进展
- `sdk_needs_review_count`
- `stalled_turn_retries`
- `last_progress_gap_seconds`

如果大面积出现这些，先判外部不稳，不急着改代码。

## 对比口径

这次和 v1 老报告比，先只看 4 件事：

1. 新路径是否真的跑通
2. 新路径是否真的走了 `chief_review + worker skills`
3. 总 findings 数量和类型是否大体可比
4. 有没有明显新增的卡死、空跑、假活

先不要急着下这些结论：

- “新架构质量已经更好”
- “新架构速度已经更快”
- “可以删掉旧链路”

这些要等 Kimi 稳定后再做更干净的影子对比。

## 通过标准

准备上 `test1` 的最低标准：

- 后端全量测试通过
- 主审开关已接入
- 两个已 skill 化 worker 能透传 `skill_id / skill_path`
- 验收命令固定为 `kimi_sdk`
- 限流参数已显式写死

当前这 5 条都已经满足。

## 当前不做

- 不启动 `test1`
- 不切 `codex_sdk`
- 不提高并发去压测 Kimi
- 不做 README 最终验收结论

# CAD Review Backend

## 默认端口与前后端约定
- Backend: `7002`
- Frontend(dev): `7001`
- Frontend API base env: `VITE_API_BASE_URL`（兼容旧变量 `VITE_API_BASE`）

## 关键环境变量
- `KIMI_PROVIDER`: 可选，`openrouter`、`code` 或 `official`
- `OPENROUTER_API_KEY`: `OpenRouter` key，`KIMI_PROVIDER=openrouter` 时必填
- `OPENROUTER_MODEL`: `OpenRouter` 模型名，默认 `openrouter/healer-alpha`
- `OPENROUTER_REASONING_ENABLED`: 是否打开推理模式，默认 `1`
- `OPENROUTER_HTTP_REFERER`: 可选，站点 URL
- `OPENROUTER_X_TITLE`: 可选，站点名称
- `KIMI_CODE_API_KEY`: `Kimi Code API` 的 key，`KIMI_PROVIDER=code` 时必填
- `KIMI_OFFICIAL_API_KEY`: `Kimi 官方 OpenAI 兼容接口` 的 key，`KIMI_PROVIDER=official` 时优先读取
- `MOONSHOT_API_KEY`: `Kimi 官方 OpenAI 兼容接口` 的兼容 key 名，`KIMI_PROVIDER=official` 时可作为回退
- `CCAD_BACKEND_PORT`: 后端端口（仅用于一致性告警，默认 `7002`）
- `CCAD_FRONTEND_DEV_PORT`: 前端开发端口（仅用于一致性告警，默认 `7001`）
- `CCAD_CORS_ORIGINS`: CORS 白名单（逗号分隔）
- `CCAD_PROJECTS_ROOT`: 项目存储根目录（默认 `{workspace}/projects`）
- `CCAD_LEGACY_WORKSPACE_PROJECTS_ROOT`: 旧存储根目录（默认 `{workspace}/projecs`）
- `CCAD_DB_BASE_DIR`: 数据库根目录（默认 `~/cad-review`）
- `CCAD_DB_PATH`: 数据库文件绝对路径（优先级高于 `CCAD_DB_BASE_DIR`）

## LLM 接口切换
- `OpenRouter`：
  - `KIMI_PROVIDER=openrouter`
  - `OPENROUTER_API_KEY=...`
  - `OPENROUTER_MODEL=openrouter/healer-alpha`
  - `AUDIT_RUNNER_PROVIDER=api`
  - `FEEDBACK_AGENT_PROVIDER=api`
- `Kimi Code API`：
  - `KIMI_PROVIDER=code`
  - `KIMI_CODE_API_KEY=...`
- `Kimi 官方 OpenAI 兼容接口`：
  - `KIMI_PROVIDER=official`
  - `KIMI_OFFICIAL_API_KEY=...`
  - 或兼容使用 `MOONSHOT_API_KEY=...`

## 存储目录迁移
- 从旧 workspace 目录 `projecs/*` 迁移到 `projects/*`：

```bash
./venv/bin/python utils/migrate_workspace_projects_root.py
./venv/bin/python utils/migrate_workspace_projects_root.py --dry-run
```

- 从 `~/cad-review/projects/{project_id}` 迁移到 workspace `projects/{project_name}`：

```bash
./venv/bin/python utils/migrate_legacy_projects.py
./venv/bin/python utils/migrate_legacy_projects.py --dry-run
```

## Runtime Cutover
- 从 2026-03-12 起，`chief_review` 是默认且主用的生产运行路径。
- legacy wrappers 仍保留，但只作为显式兼容兜底：
  - `run_dimension_worker_wrapper`
  - `run_index_worker_wrapper`
  - `run_material_worker_wrapper`
  - `run_relationship_worker_wrapper`
- legacy stage prompt 仍可被兼容入口调用，但不再是 chief/native runtime 的主提示来源。

## Chief Review 影子验收
- 从 2026-03-12 起，影子验收脚本统一使用 `utils/manual_check_ai_review_flow.py`，建议显式带上 `--provider-mode api` 或 `--provider-mode openrouter`，不要依赖默认 provider。
- 推荐命令：

```bash
cd cad-review-backend
./venv/bin/python utils/manual_check_ai_review_flow.py --project-id <project_id> --provider-mode api --run-mode legacy
./venv/bin/python utils/manual_check_ai_review_flow.py --project-id <project_id> --provider-mode api --run-mode chief_review
./venv/bin/python utils/manual_check_ai_review_flow.py --project-id <project_id> --provider-mode api --run-mode shadow_compare
```

- cutover gate：
  - `overlap_ratio >= 0.80`
  - `legacy_only_ratio <= 0.20`
  - `chief_review_only_ratio <= 0.20`
  - `duration_delta_seconds <= 30`
  - `ready_for_cutover == true`

- 失败条件：
  - 任一路径未完成或未成功落到 `done/completed`
  - 两条影子路径落到同一个 `audit_version` 或没有真正分叉出不同 `pipeline_mode`
  - 主审路径相对旧路径新增太多问题，或丢失太多旧问题
  - 主审路径耗时回归超过 30 秒

- 说明：
  - `shadow_compare` 现在输出的是业务级对比信号，而不只是框架接通。
  - 本地 `manual_check_ai_review_flow.py` 的“计划预览”仍然会触发较重的关系发现；做真实人工验收时建议显式加更长的 `--wait-seconds`。

## Assignment Final Review 正式验收
- 从 2026-03-12 起，`assignment_final_review` 是“主审派单 -> 副审单卡执行 -> 终审复核 -> 汇总整理 -> 最终 grounded 报告”的正式验收路径。
- 推荐命令：

```bash
cd cad-review-backend
./venv/bin/python utils/manual_check_ai_review_flow.py \
  --project-id proj_20260309231506_001af8d5 \
  --start-audit \
  --run-mode assignment_final_review \
  --provider-mode api \
  --wait-seconds 180
```

- 通过标准：
  - `visible_worker_card_count <= assignment_count`
  - 运行态里能看到独立 `final_review` 阶段
  - 运行态或最终结果里能确认 `organizer` 产出了 Markdown
  - `grounded_final_issue_count > 0` 时才允许认为最终报告具备可落图证据
  - `runtime_report.mode == marked`，且 marked report 使用的是最终 issue 的 anchors，不是只靠文字位置兜底

- 验收脚本会额外输出 `checks.assignment_final_review`，重点看：
  - `worker_card_not_exceed_assignment_count`
  - `final_review_visible`
  - `organizer_markdown_output`
  - `grounded_final_issue_count`
  - `marked_report_generated`

- 注意：
  - 只有 `sheet_no` 或 `evidence_pack_id` 不算真正通过，最终问题必须带 grounded anchors。
  - 当前 marked report 会优先吃 `highlight_region.bbox_pct`，其次才是 `global_pct`。
  - 如果 `--provider-mode api` 缺少可用密钥，脚本会失败并把原因写进 `.artifacts/manual-checks/*.json`。

## Chief Review Worker Skills
- 当前已 skill 化的副审能力：`index_reference`、`material_semantic_consistency`、`node_host_binding`、`elevation_consistency`、`spatial_consistency`
- skill 资源目录：`agents/review_worker/skills/*/SKILL.md`
- 运行时骨架仍在 `services/audit_runtime/*`，这轮没有把 `chief_review / runner / observer / recovery` 抽成 skill

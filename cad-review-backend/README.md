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

## Chief Review 影子验收
- 从 2026-03-12 起，影子验收脚本统一使用 `utils/manual_check_ai_review_flow.py`，建议显式带上 `--provider-mode api` 或 `--provider-mode openrouter`，不要依赖默认 provider。
- 推荐命令：

```bash
cd cad-review-backend
./venv/bin/python utils/manual_check_ai_review_flow.py --project-id <project_id> --provider-mode api --run-mode legacy
./venv/bin/python utils/manual_check_ai_review_flow.py --project-id <project_id> --provider-mode api --run-mode chief_review
./venv/bin/python utils/manual_check_ai_review_flow.py --project-id <project_id> --provider-mode api --run-mode shadow_compare
```

- 当前限制：
  - `shadow_compare` 现在验证的是“影子框架 + API Runner 接通”，不是“新旧主流程已经分叉后的业务对比”。
  - 本地 `manual_check_ai_review_flow.py` 的“计划预览”会触发较重的关系发现，因此 `shadow_compare` 实跑可能耗时很长；如果要做真实人工对比，先完成主流程切换，再用更长的 `--wait-seconds` 跑。

## Chief Review Worker Skills
- 当前已 skill 化的副审能力：`index_reference`、`material_semantic_consistency`
- skill 资源目录：`agents/review_worker/skills/*/SKILL.md`
- 运行时骨架仍在 `services/audit_runtime/*`，这轮没有把 `chief_review / runner / observer / recovery` 抽成 skill

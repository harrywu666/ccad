# CAD Review Backend

## 默认端口与前后端约定
- Backend: `7002`
- Frontend(dev): `7001`
- Frontend API base env: `VITE_API_BASE_URL`（兼容旧变量 `VITE_API_BASE`）

## 关键环境变量
- `KIMI_PROVIDER`: 可选，`code` 或 `official`，默认 `official`
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

## Kimi 接口切换
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
- 从 2026-03-11 起，影子验收脚本统一使用 `utils/manual_check_ai_review_flow.py`，建议显式带上 `--provider-mode kimi_sdk`，不要依赖默认 provider。
- 推荐命令：

```bash
cd cad-review-backend
./venv/bin/python utils/manual_check_ai_review_flow.py --project-id <project_id> --provider-mode kimi_sdk --run-mode legacy
./venv/bin/python utils/manual_check_ai_review_flow.py --project-id <project_id> --provider-mode kimi_sdk --run-mode chief_review
./venv/bin/python utils/manual_check_ai_review_flow.py --project-id <project_id> --provider-mode kimi_sdk --run-mode shadow_compare
```

- 已确认的本地证据：
  - 项目 `proj_20260309231506_001af8d5` 的最近一次正式审图记录使用的是 `kimi_sdk`，`audit_version=1`，开始时间 `2026-03-10 23:44:16`，结束时间 `2026-03-11 00:39:35`。
  - 现有 HTTP 验收报告 `[proj_20260309231506_001af8d5-kimi_sdk-http_127.0.0.1_7002-codex-switch-check.json](/Users/harry/@dev/ccad/.artifacts/manual-checks/proj_20260309231506_001af8d5-kimi_sdk-http_127.0.0.1_7002-codex-switch-check.json)` 证明 `provider_mode=kimi_sdk` 已经能打通到后端验收链路。
  - 影子框架相关自动化测试已覆盖 `legacy / chief_review / shadow_compare` 三种运行模式。

- 当前限制：
  - `shadow_compare` 现在验证的是“影子框架 + Kimi SDK Runner 接通”，不是“新旧主流程已经分叉后的业务对比”。
  - 原因是截至 `2026-03-11`，后端主流程还没有真正消费 `AUDIT_CHIEF_REVIEW_ENABLED`；也就是说，`chief_review` 模式的入口和报告链路已经有了，但 orchestrator 还没切到新的主审路径。
  - 本地 `manual_check_ai_review_flow.py` 的“计划预览”会触发较重的关系发现，因此 `shadow_compare` 实跑可能耗时很长；如果要做真实人工对比，先完成主流程切换，再用更长的 `--wait-seconds` 跑。

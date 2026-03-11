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

## Chief Review Worker Skills
- 当前已 skill 化的副审能力：`index_reference`、`material_semantic_consistency`
- skill 资源目录：`agents/review_worker/skills/*/SKILL.md`
- 运行时骨架仍在 `services/audit_runtime/*`，这轮没有把 `chief_review / runner / observer / recovery` 抽成 skill

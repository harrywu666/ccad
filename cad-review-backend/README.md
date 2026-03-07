# CAD Review Backend

## 默认端口与前后端约定
- Backend: `7002`
- Frontend(dev): `7001`
- Frontend API base env: `VITE_API_BASE_URL`（兼容旧变量 `VITE_API_BASE`）

## 关键环境变量
- `KIMI_CODE_API_KEY`: 必填，Kimi API Key
- `CCAD_BACKEND_PORT`: 后端端口（仅用于一致性告警，默认 `7002`）
- `CCAD_FRONTEND_DEV_PORT`: 前端开发端口（仅用于一致性告警，默认 `7001`）
- `CCAD_CORS_ORIGINS`: CORS 白名单（逗号分隔）
- `CCAD_PROJECTS_ROOT`: 项目存储根目录（默认 `{workspace}/projects`）
- `CCAD_LEGACY_WORKSPACE_PROJECTS_ROOT`: 旧存储根目录（默认 `{workspace}/projecs`）
- `CCAD_DB_BASE_DIR`: 数据库根目录（默认 `~/cad-review`）
- `CCAD_DB_PATH`: 数据库文件绝对路径（优先级高于 `CCAD_DB_BASE_DIR`）

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

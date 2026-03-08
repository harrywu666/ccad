# 索引问题自动定位实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 让索引类问题在审核生成时自动绑定到具体图纸和具体坐标，前端查看问题时直接打开源图并自动定位到出错索引，即使目标图不存在也能稳定展示。

**架构：** 后端新增“问题图纸匹配记录”表，并在索引审核产出 `AuditResult` 后立即落库 `source/target` 两侧的图纸与锚点。前端改为通过“问题预览接口”获取精确图纸和定位信息，系统定位标记作为只读叠加层显示，不与人工标注混用。

**技术栈：** FastAPI、SQLAlchemy、SQLite、React 19、Vite、Konva、pytest、ESLint

---

### 任务 1：补齐后端持久化模型与轻量迁移

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/models.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/database.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_issue_preview_api.py`

**步骤 1：编写失败的测试**

在 `test_issue_preview_api.py` 中新增用例：

- 创建 `AuditResult`
- 创建旧版 `Drawing`
- 预期数据库初始化后存在新表 `audit_issue_drawings`
- 可插入 `source` 侧记录并通过唯一约束约束同一 `(audit_result_id, match_side)`

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && pytest tests/test_issue_preview_api.py -q
```

预期：

- FAIL，提示表不存在或模型不存在

**步骤 3：编写最小实现**

实现内容：

- 在 `models.py` 新增 `AuditIssueDrawing` 模型
- 在 `database.py::_ensure_runtime_columns()` 中追加建表逻辑
- 为表增加 `UNIQUE(audit_result_id, match_side)`

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && pytest tests/test_issue_preview_api.py -q
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/models.py cad-review-backend/database.py cad-review-backend/tests/test_issue_preview_api.py
git commit -m "feat: add audit issue drawing persistence"
```

### 任务 2：在索引审核阶段写入 source/target 图纸匹配记录

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py`
- 新建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/issue_preview.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_issue_preview_api.py`

**步骤 1：编写失败的测试**

新增场景：

- 图纸 `A6.00` 存在
- 其 JSON 中 `索引3` 的 `target_sheet` 为 `A06.00a`
- 系统生成索引错误
- 同时为该 `AuditResult` 自动生成一条 `match_side=source` 的记录，带 `drawing_id`、`drawing_data_version`、`index_no=3`、`anchor_json.global_pct`
- 不生成有效的 `target` 图纸记录

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && pytest tests/test_issue_preview_api.py -q
```

预期：

- FAIL，提示没有持久化问题图纸匹配记录

**步骤 3：编写最小实现**

实现内容：

- 在 `services/audit/issue_preview.py` 中封装：
  - `parse_issue_anchors(result)`
  - `resolve_drawing_for_sheet(project_id, sheet_no, db, prefer_data_version=None)`
  - `upsert_issue_drawing_match(...)`
- 在 `index_audit.py` 生成每条 `AuditResult` 后调用该服务
- 规则：
  - `source` 永远优先由源图锚点落库
  - `target` 仅在目标图真实存在且能解析到具体 `drawing_id` 时落库为 `matched`
  - 不根据“疑似纠正图号”去消除错误

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && pytest tests/test_issue_preview_api.py -q
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit/index_audit.py cad-review-backend/services/audit/issue_preview.py cad-review-backend/tests/test_issue_preview_api.py
git commit -m "feat: persist source issue anchors for index audit"
```

### 任务 3：新增问题预览接口并绑定历史图纸版本

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/drawings.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/issue_preview.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_issue_preview_api.py`

**步骤 1：编写失败的测试**

新增接口场景：

- 调用 `GET /api/projects/{project_id}/audit/results/{result_id}/preview`
- 返回 `source` 图纸、`target` 图纸、anchor、缺失原因
- 当项目后来重传了新的 `A6.00` 时，旧审核结果仍返回旧 `drawing_id`

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && pytest tests/test_issue_preview_api.py -q
```

预期：

- FAIL，提示接口不存在或返回内容不完整

**步骤 3：编写最小实现**

实现内容：

- 在 `audit.py` 新增 preview 响应模型与路由
- 从 `AuditIssueDrawing` 读取 source/target 记录
- 统一输出：
  - `issue`
  - `source`
  - `target`
  - `missing_reason`
- 若历史 `drawing_id` 已失效则返回明确错误，不静默切换到最新图纸

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && pytest tests/test_issue_preview_api.py -q
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/routers/audit.py cad-review-backend/routers/drawings.py cad-review-backend/services/audit/issue_preview.py cad-review-backend/tests/test_issue_preview_api.py
git commit -m "feat: add issue preview API for precise drawing location"
```

### 任务 4：前端改为消费问题预览接口并自动定位 source 图

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/api/index.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/types/index.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/ProjectStepAudit.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/InlineDrawingPreviewPanel.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/annotated-canvas/AnnotatedDrawingPreviewCanvas.tsx`
- 新建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/annotated-canvas/useIssueFocus.ts`

**步骤 1：编写失败的测试**

如果前端暂时没有单测框架，则先补一个最小的纯函数测试入口；否则至少定义验收标准：

- 点开该索引问题时默认展示 source 图 `A6.00`
- target 图不存在时，B 按钮不显示或禁用
- 画布初次加载后自动定位到 `anchor.global_pct`
- 页面说明明确这是“目标图不存在”，不是“找不到任何图”

建议新增测试文件：

- `src/pages/ProjectDetail/components/project-detail/annotated-canvas/useIssueFocus.test.ts`

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && pnpm lint
```

若已补充前端测试框架，再运行对应测试命令。

预期：

- 现状下无法通过新的类型和接口约束

**步骤 3：编写最小实现**

实现内容：

- `api/index.ts` 增加 `getAuditResultPreview`
- `ProjectStepAudit.tsx` 打开问题时改为请求 preview，而不是自己 `pickBestDrawing`
- `AnnotatedDrawingPreviewCanvas.tsx` 增加只读系统定位标记和首次自动聚焦
- `useIssueFocus.ts` 封装 `global_pct -> viewport` 的聚焦逻辑
- 系统定位标记不写入 `drawing_annotations`

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && pnpm lint
cd /Users/harry/@dev/ccad/cad-review-frontend && pnpm build
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-frontend/src/api/index.ts cad-review-frontend/src/types/index.ts cad-review-frontend/src/pages/ProjectDetail/components/project-detail/ProjectStepAudit.tsx cad-review-frontend/src/pages/ProjectDetail/components/project-detail/InlineDrawingPreviewPanel.tsx cad-review-frontend/src/pages/ProjectDetail/components/project-detail/annotated-canvas/AnnotatedDrawingPreviewCanvas.tsx cad-review-frontend/src/pages/ProjectDetail/components/project-detail/annotated-canvas/useIssueFocus.ts
git commit -m "feat: focus issue preview on source drawing anchors"
```

### 任务 5：做回归验证，锁定“目标图不存在但源图可定位”的行为

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_issue_preview_api.py`
- 可选修改：`/Users/harry/@dev/ccad/cad-review-frontend/e2e/smoke.spec.ts`

**步骤 1：编写失败的测试**

补齐回归场景：

- `A6.00` -> `A06.00a` 时报错成立
- preview 默认返回 source 图和 source anchor
- target 缺失时不会把问题吞掉，也不会把图切成“无图可看”
- 重传同图号新版本后，旧审核版本 preview 仍指向旧图

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && pytest tests/test_issue_preview_api.py -q
```

如补 E2E，再运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && pnpm exec playwright test e2e/smoke.spec.ts
```

预期：

- FAIL，直到所有链路收敛

**步骤 3：编写最小实现**

实现内容：

- 修正遗漏的接口字段、视图文案或版本绑定问题
- 确保 preview 接口和前端聚焦逻辑稳定通过

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && pytest tests/test_issue_preview_api.py -q
cd /Users/harry/@dev/ccad/cad-review-frontend && pnpm lint
cd /Users/harry/@dev/ccad/cad-review-frontend && pnpm build
```

如已具备 Playwright 运行条件，再运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && pnpm exec playwright test e2e/smoke.spec.ts
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/tests/test_issue_preview_api.py cad-review-frontend/e2e/smoke.spec.ts
git commit -m "test: lock issue preview behavior for missing target drawings"
```

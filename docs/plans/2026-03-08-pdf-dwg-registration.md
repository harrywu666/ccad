# PDF-DWG 坐标配准实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 将所有需要展示给用户的审核定位统一转换为 PDF 页面坐标，解决 DWG 结构坐标与 PDF 预览图错位的问题。

**架构：** 后端新增 registration 数据层，将 `DWG layout` 的纸面坐标映射到 `PDF page` 坐标；审核结果保留 `layout_anchor`，并统一产出 `pdf_anchor`。前端与报告层仅消费 `pdf_anchor`，不再直接使用 DWG 百分比坐标。

**技术栈：** FastAPI、SQLAlchemy、SQLite、ezdxf、PyMuPDF、React 19、Konva、pytest、ESLint

---

### 任务 1：定义 registration 数据模型与回填入口

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/models.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/database.py`
- 新建：`/Users/harry/@dev/ccad/cad-review-backend/services/registration_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_registration_service.py`

**步骤 1：编写失败的测试**

在 `test_registration_service.py` 中新增：

- 新表 `drawing_layout_registrations` 可创建
- 可保存 `layout_page_range_json`、`pdf_page_size_json`、`transform_json`
- 同一 `(drawing_id, layout_name, pdf_page_index)` 唯一

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_registration_service.py -q
```

预期：
- FAIL，提示模型或表不存在

**步骤 3：编写最小实现**

实现内容：

- 在 `models.py` 新增 `DrawingLayoutRegistration`
- 在 `database.py` 添加轻量建表逻辑
- 在 `registration_service.py` 添加最小 CRUD 接口

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_registration_service.py -q
```

预期：
- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/models.py cad-review-backend/database.py cad-review-backend/services/registration_service.py cad-review-backend/tests/test_registration_service.py
git commit -m "feat: add layout to pdf registration model"
```

### 任务 2：提取并持久化 layout 纸面范围与 PDF 页面尺寸

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/dxf_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/layout_json_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/drawing_ingest/drawings_ingest_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/drawings.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_coordinate_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_registration_service.py`

**步骤 1：编写失败的测试**

新增场景：

- DWG layout 可提取 `layout_page_range`
- PDF 页面可提取 `pdf_page_width/pdf_page_height`
- 旧 JSON 缺失 `layout_page_range` 时可从源 DWG 回填

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_coordinate_service.py tests/test_registration_service.py -q
```

预期：
- FAIL

**步骤 3：编写最小实现**

实现内容：

- `dxf_service.py` 输出 `layout_page_range`
- `drawings_ingest_service.py`/`routers/drawings.py` 记录 PDF 页面像素尺寸
- `layout_json_service.py` 统一负责旧 JSON 回填

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_coordinate_service.py tests/test_registration_service.py -q
```

预期：
- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/dxf_service.py cad-review-backend/services/layout_json_service.py cad-review-backend/services/drawing_ingest/drawings_ingest_service.py cad-review-backend/routers/drawings.py cad-review-backend/tests/test_coordinate_service.py cad-review-backend/tests/test_registration_service.py
git commit -m "feat: capture layout and pdf page geometry"
```

### 任务 3：实现一级 registration 变换并产出 pdf_anchor

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/registration_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/issue_preview.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_registration_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_issue_preview_api.py`

**步骤 1：编写失败的测试**

新增场景：

- 给定 `layout_page_range` 与 `pdf_page_size`
- 能把 `layout_anchor` 转换为 `pdf_anchor`
- `issue_preview` 返回 `layout_anchor` 和 `pdf_anchor`
- 前端消费时只需要 `pdf_anchor`

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_registration_service.py tests/test_issue_preview_api.py -q
```

预期：
- FAIL

**步骤 3：编写最小实现**

实现内容：

- `registration_service.py` 实现一级直接纸面配准
- `issue_preview.py` 在返回 preview 前确保 `pdf_anchor` 已生成
- `index_audit.py` 保存 `layout_anchor`
- `issue_preview.py` 负责按 registration 生成最终 `pdf_anchor`

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_registration_service.py tests/test_issue_preview_api.py -q
```

预期：
- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/registration_service.py cad-review-backend/services/audit/issue_preview.py cad-review-backend/services/audit/index_audit.py cad-review-backend/tests/test_registration_service.py cad-review-backend/tests/test_issue_preview_api.py
git commit -m "feat: map layout anchors to pdf anchors"
```

### 任务 4：为低置信度配准增加降级与标记

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/registration_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/issue_preview.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/audit.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_registration_service.py`

**步骤 1：编写失败的测试**

新增场景：

- registration 缺失时，preview 只返回 `layout_anchor`
- registration 置信度低时，返回 `pdf_anchor.confidence < 0.6`
- API 明确标记 `missing_reason` 或 `anchor_status`

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_registration_service.py -q
```

预期：
- FAIL

**步骤 3：编写最小实现**

实现内容：

- registration 服务输出 `confidence`
- preview 接口返回 `anchor_status`
- 对无法可靠映射的场景，避免伪造精确点

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_registration_service.py -q
```

预期：
- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/registration_service.py cad-review-backend/services/audit/issue_preview.py cad-review-backend/routers/audit.py cad-review-backend/tests/test_registration_service.py
git commit -m "feat: add registration confidence and fallback states"
```

### 任务 5：前端切换为只消费 pdf_anchor

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/types/index.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/api/index.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/ProjectStepAudit.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/InlineDrawingPreviewPanel.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/annotated-canvas/useIssueFocus.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/annotated-canvas/AnnotatedDrawingPreviewCanvas.tsx`

**步骤 1：编写失败的测试**

若前端没有单测框架，则至少定义验收基线：

- 有 `pdf_anchor` 时，十字严格按 PDF 页面坐标定位
- 低置信度时，显示“估计位置”
- 无可靠 `pdf_anchor` 时，不再画精确十字

**步骤 2：运行验证命令**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && pnpm lint
```

预期：
- 现状下需要调整类型和消费逻辑

**步骤 3：编写最小实现**

实现内容：

- 扩展 preview 类型定义
- `useIssueFocus` 改为只看 `pdf_anchor`
- 画布根据 `confidence` 决定是精确十字还是低置信度提示

**步骤 4：运行验证命令**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && pnpm lint
cd /Users/harry/@dev/ccad/cad-review-frontend && pnpm build
```

预期：
- PASS

**步骤 5：提交**

```bash
git add cad-review-frontend/src/types/index.ts cad-review-frontend/src/api/index.ts cad-review-frontend/src/pages/ProjectDetail/components/project-detail/ProjectStepAudit.tsx cad-review-frontend/src/pages/ProjectDetail/components/project-detail/InlineDrawingPreviewPanel.tsx cad-review-frontend/src/pages/ProjectDetail/components/project-detail/annotated-canvas/useIssueFocus.ts cad-review-frontend/src/pages/ProjectDetail/components/project-detail/annotated-canvas/AnnotatedDrawingPreviewCanvas.tsx
git commit -m "feat: render issue focus from pdf anchors"
```

### 任务 6：真实项目回归验证与旧数据迁移

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/issue_preview.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/registration_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_issue_preview_api.py`
- 文档：`/Users/harry/@dev/ccad/docs/plans/2026-03-08-pdf-dwg-registration-design.md`

**步骤 1：编写失败的测试**

新增旧数据场景：

- 历史 `audit_issue_drawings` 只有旧 `layout/global_pct`
- preview 首次访问时自动生成 registration 并刷新 `pdf_anchor`

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_issue_preview_api.py -q
```

预期：
- FAIL

**步骤 3：编写最小实现**

实现内容：

- 在 preview 时对旧记录做懒迁移
- 注册并缓存 registration 结果
- 更新旧锚点到 `pdf_anchor`

**步骤 4：运行测试和真实验证**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_registration_service.py tests/test_coordinate_service.py tests/test_issue_preview_api.py tests/test_drawing_annotations_api.py tests/test_audit_feedback_api.py tests/test_skill_pack_injection.py -q
cd /Users/harry/@dev/ccad/cad-review-frontend && pnpm lint
cd /Users/harry/@dev/ccad/cad-review-frontend && pnpm build
```

并在真实项目 `all-dwg-batch-upload-test` 中验证：

- `A6.00 / 索引3`
- `A6.02 / 索引2`
- `A6.02a / 索引3`

预期：
- 三条问题在 PDF 页面上明显收敛到正确符号附近

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit/issue_preview.py cad-review-backend/services/registration_service.py cad-review-backend/tests/test_issue_preview_api.py docs/plans/2026-03-08-pdf-dwg-registration-design.md
git commit -m "feat: migrate issue previews to pdf coordinate registration"
```

### 任务 7：为 AI 审核结果统一输出 pdf_anchor

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_issue_preview_api.py`

**步骤 1：编写失败的测试**

新增场景：

- 索引、尺寸、材料问题最终都能返回 `pdf_anchor`
- 没有 registration 时不会伪造高置信度锚点

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_issue_preview_api.py -q
```

预期：
- FAIL

**步骤 3：编写最小实现**

实现内容：

- 审核服务统一在问题预览层或产出层补 `pdf_anchor`
- 明确 `origin = dwg|pdf|ai`
- 使后续 AI 截图和导出都消费同一锚点

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_issue_preview_api.py tests/test_coordinate_service.py -q
```

预期：
- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit/index_audit.py cad-review-backend/services/audit/dimension_audit.py cad-review-backend/services/audit/material_audit.py cad-review-backend/services/audit_service.py cad-review-backend/tests/test_issue_preview_api.py
git commit -m "feat: unify audit outputs on pdf anchors"
```

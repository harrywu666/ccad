# 子 Agent 精确定位锁定实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 把“问题必须自带精确定位和云线区域”前移到子 Agent 运行阶段，作为正式问题成立的硬条件。

**架构：** 先修改子 Agent 的输出合同，再在运行时加硬校验和重试，让索引/尺寸/材料 Agent 只有在同时产出问题内容和定位框时才能落结果。前端只负责展示已经锁死的定位，不再负责猜位置。

**技术栈：** FastAPI、SQLAlchemy、现有 audit runtime、React、Konva、pytest、Vitest

---

### 任务 1：补“精确定位问题”的通用合同

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/finding_schema.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_grounded_finding_schema.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_finding_schema.py`

**步骤 1：编写失败测试**

写测试覆盖下面几种情况：
- 没有 `anchor`
- 没有 `highlight_region`
- `highlight_region` 宽高无效
- `sheet_no` 缺失
- 合格问题同时带有 `anchor + highlight_region + confidence`
- 存在统一重试上限常量 `GROUNDING_MAX_RETRY = 2`

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_grounded_finding_schema.py tests/test_finding_schema.py
```

预期：
- 新测试失败

**步骤 3：编写最小实现**

在 `finding_schema.py` 里新增或收紧：
- 通用 grounded finding 校验函数
- 对正式 finding 的硬校验
- 统一重试上限常量 `GROUNDING_MAX_RETRY = 2`

这个常量后面所有 Agent 和运行时都要引用，不能各自写死自己的次数。

**步骤 4：运行测试验证通过**

运行同一条命令，预期：
- PASS

**步骤 5：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/finding_schema.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_grounded_finding_schema.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_finding_schema.py
git commit -m "feat: require grounded finding contract"
```

---

### 任务 2：确认多锚点落库格式是否真的成立

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/issue_preview.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_service.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_evidence_anchor_array_schema.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_issue_preview_api.py`

**步骤 1：编写失败测试**

覆盖：
- `evidence_json.anchors` 能稳定读取多个锚点
- 老数据如果只有单锚点格式，仍然能兼容读取
- 写入新数据时，不会把多个锚点压回一个主锚点

**步骤 2：运行测试验证失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_evidence_anchor_array_schema.py tests/test_issue_preview_api.py
```

**步骤 3：编写最小实现**

实现点：
- 明确 `evidence_json.anchors` 的标准结构就是数组
- 如果当前仍有单锚点兼容格式，补一层读兼容
- 所有后续 grouped preview 逻辑都以数组为准

**步骤 4：运行测试验证通过**

运行同一条命令，预期：
- PASS

**步骤 5：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-backend/services/audit/issue_preview.py /Users/harry/@dev/ccad/cad-review-backend/services/audit_service.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_evidence_anchor_array_schema.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_issue_preview_api.py
git commit -m "feat: standardize evidence anchor array schema"
```

---

### 任务 3：索引 Agent 强制输出精确定位

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/layout_json_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_index_worker_ai_review.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_index_grounded_findings.py`

**步骤 1：编写失败测试**

覆盖：
- 索引问题没有 `highlight_region` 时不能落结果
- 索引问题文本和图上二次读取的索引号不一致时不能落结果
- 合法索引问题能生成稳定的 `anchor + highlight_region`

**步骤 2：运行测试验证失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_index_grounded_findings.py tests/test_index_worker_ai_review.py
```

**步骤 3：编写最小实现**

实现点：
- 索引 Agent 在输出前强制生成 bbox
- 二次核对索引号和目标图号
- 不一致时只写内部日报，不在 Agent 内部自己循环重试
- 统一交给运行时重试管理，不直接写入 `audit_results`

**步骤 4：运行测试验证通过**

运行同一条命令，预期：
- PASS

**步骤 5：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py /Users/harry/@dev/ccad/cad-review-backend/services/audit_service.py /Users/harry/@dev/ccad/cad-review-backend/services/layout_json_service.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_index_grounded_findings.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_index_worker_ai_review.py
git commit -m "feat: lock index findings to grounded anchors"
```

---

### 任务 4：尺寸 Agent 强制输出精确定位

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/issue_preview.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dimension_finding_v2.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dimension_grounded_findings.py`

**步骤 1：编写失败测试**

覆盖：
- 模糊描述但无具体 bbox 的尺寸问题不能落结果
- 只有一侧有定位框、另一侧没有时不能落结果
- 尺寸对象 ID 能反推出稳定 bbox 时允许落结果

**步骤 2：运行测试验证失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_dimension_grounded_findings.py tests/test_dimension_finding_v2.py
```

**步骤 3：编写最小实现**

实现点：
- 尺寸问题必须落到对象 ID / 文本 bbox / 尺寸链局部框
- 没框时只写内部日报，不在尺寸 Agent 内部自己循环重试
- 统一交给运行时重试管理

**步骤 4：运行测试验证通过**

运行同一条命令，预期：
- PASS

**步骤 5：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py /Users/harry/@dev/ccad/cad-review-backend/services/audit/issue_preview.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_dimension_grounded_findings.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_dimension_finding_v2.py
git commit -m "feat: require grounded dimension findings"
```

---

### 任务 5：材料 Agent 强制输出精确定位

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/issue_preview.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_material_grounded_findings.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_material_finding_v2.py`

**步骤 1：编写失败测试**

覆盖：
- 材料问题只有文字没有定位框时不能落结果
- 材料引线/文字块能定位到 bbox 时允许落结果

**步骤 2：运行测试验证失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_material_grounded_findings.py tests/test_material_finding_v2.py
```

**步骤 3：编写最小实现**

让材料 Agent 也遵守 grounded finding 合同。

额外要求：
- 材料 Agent 不在内部自己套第二层重试
- 定位失败只上报，不自己无限试

**步骤 4：运行测试验证通过**

运行同一条命令，预期：
- PASS

**步骤 5：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py /Users/harry/@dev/ccad/cad-review-backend/services/audit/issue_preview.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_material_grounded_findings.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_material_finding_v2.py
git commit -m "feat: require grounded material findings"
```

---

### 任务 6：把“没定位成功”变成运行时统一重试，不是结果落库

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_runner.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_reports.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_grounding_retry_loop.py`

**步骤 1：编写失败测试**

覆盖：
- 子 Agent 产出问题但没 `highlight_region` 时，不写正式结果
- 同时写一条内部日报，说明“定位失败，正在重试”
- 重试成功后才允许落结果
- 超过 `GROUNDING_MAX_RETRY = 2` 后，不再继续重试
- 子 Agent 自己不会再叠加一层内部重试

**步骤 2：运行测试验证失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_grounding_retry_loop.py
```

**步骤 3：编写最小实现**

把“无定位输出”当成运行时统一管理的失败，而不是业务问题。

实现时要明确两点：
- 子 Agent 内部不再自己做定位重试
- 全部定位重试次数由 `agent_runner.py` 统一管理

这样可以避免：
- 子 Agent 重试 N 次
- 运行时又重试 N 次
- 最后实际变成 N² 次

**步骤 4：运行测试验证通过**

运行同一条命令，预期：
- PASS

**步骤 5：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_runner.py /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_reports.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_grounding_retry_loop.py
git commit -m "feat: retry subagent grounding before committing findings"
```

---

### 任务 7：一组问题强制带多个定位框

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/issue_preview.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_batch_preview_requires_all_grounded_anchors.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_issue_preview_api.py`

**步骤 1：编写失败测试**

覆盖：
- 一组问题中有 3 个子问题，就要返回 3 个定位框
- 其中某个子问题没框时，这组不算完整

**步骤 2：运行测试验证失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_batch_preview_requires_all_grounded_anchors.py tests/test_issue_preview_api.py
```

**步骤 3：编写最小实现**

批量预览接口不再“有几个画几个”，而是要求整组完整。

**步骤 4：运行测试验证通过**

运行同一条命令，预期：
- PASS

**步骤 5：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-backend/routers/audit.py /Users/harry/@dev/ccad/cad-review-backend/services/audit/issue_preview.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_batch_preview_requires_all_grounded_anchors.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_issue_preview_api.py
git commit -m "feat: require complete grounded anchors for grouped preview"
```

---

### 任务 8：前端只展示子 Agent 已经锁死的云线

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/ProjectStepAudit.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/InlineDrawingPreviewPanel.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/annotated-canvas/AnnotatedDrawingPreviewCanvas.tsx`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/GroundedIssuePreview.test.tsx`

**步骤 1：编写失败测试**

覆盖：
- 多个子问题会同时显示多个云线
- 不再展示“估计位置”当成正式证据
- 没有 grounded 框的数据不会显示成正式问题预览

**步骤 2：运行测试验证失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/pages/ProjectDetail/components/__tests__/GroundedIssuePreview.test.tsx
```

**步骤 3：编写最小实现**

前端只显示后端锁死的框，不再替后端猜位置。

**步骤 4：运行测试验证通过**

运行同一条命令，预期：
- PASS

**步骤 5：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/ProjectStepAudit.tsx /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/InlineDrawingPreviewPanel.tsx /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/annotated-canvas/AnnotatedDrawingPreviewCanvas.tsx /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/GroundedIssuePreview.test.tsx
git commit -m "feat: render only grounded issue highlights"
```

---

### 任务 9：真实验收

**文件：**
- 使用现有运行链路
- 验收记录写入：`/Users/harry/@dev/ccad/.artifacts/manual-checks/`

**步骤 1：启动真实审图**

运行：

```bash
cd /Users/harry/@dev/ccad
curl --noproxy '*' -fsS -X POST http://127.0.0.1:7002/api/projects/proj_20260309231506_001af8d5/audit/start -H 'Content-Type: application/json' -d '{"provider_mode":"kimi_sdk"}'
```

**步骤 2：验证关键现象**

检查：
- 索引问题描述和右侧云线框一致
- 同图多问题时，右侧出现多个框
- 尺寸/材料问题没有“模糊描述但无框”的正式结果

**步骤 3：输出验收结论**

必须明确回答：
- 哪些问题被精确落位了
- 是否还存在“问题成立但没圈线”的情况
- 如果还有，是哪类 Agent 还没收紧

**步骤 4：提交**

```bash
git add /Users/harry/@dev/ccad/.artifacts/manual-checks
git commit -m "test: validate grounded issue highlighting in real project"
```

# 索引审核统一语义提取实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 为索引审核补齐 `detail_titles` 统一语义层，让目标图是否存在同编号回指对象的判断不再只依赖 `indexes` 和 `title_blocks`，从而修复 `G0.03 -> G0.04 / A1` 这类误报。

**架构：** 在 DXF 提取阶段新增 `detail_titles` 语义对象，持久化到布局 JSON；在索引审核阶段构建统一的 `target_reference_labels` 集合进行判定，并把命中的实体类型和来源写入证据。AI 不参与主链路，只作为后续歧义兜底扩展点保留。

**技术栈：** FastAPI、SQLAlchemy、Python、pytest、React、TypeScript、DWG/DXF 结构化提取

---

### 任务 1：为 `detail_titles` 补提取测试

**文件：**
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dxf_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_layout_json_service.py`

**步骤 1：编写失败的测试**

新增两个测试：

1. `test_extracts_detail_titles_from_modelspace_blocks`
   - 构造一个 `INSERT`
   - 属性包含 `DN=A1`、`TITLE1=D01 前厅门`、`TITLE3=DETAIL - LOBBY DOOR`
   - 预期提取结果中新增一条 `detail_title`

2. `test_backfill_layout_json_adds_detail_titles`
   - 给旧 JSON 输入不含 `detail_titles`
   - 预期回填后包含 `detail_titles`

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_dxf_service.py tests/test_layout_json_service.py -q
```

预期：

- FAIL，提示 `detail_titles` 未提取或未回填

**步骤 3：编写最小实现**

实现内容：

- 在提取器中识别含 `DN/TITLE1/TITLE2/TITLE3/SHEETNO` 的候选标题块
- 输出结构化 `detail_titles`
- 旧 JSON 回填逻辑支持补写该字段

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_dxf_service.py tests/test_layout_json_service.py -q
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/tests/test_dxf_service.py cad-review-backend/tests/test_layout_json_service.py
git commit -m "test: cover detail title extraction"
```

### 任务 2：在 DXF 提取与 JSON 回填中加入 `detail_titles`

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/dxf_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/layout_json_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dxf_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_layout_json_service.py`

**步骤 1：编写失败的测试**

如果任务 1 中测试还不够细，再补一条：

- `detail_titles` 应保留：
  - `label`
  - `title_lines`
  - `title_text`
  - `block_name`
  - `layer`
  - `attrs`
  - `position`
  - `source`

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_dxf_service.py tests/test_layout_json_service.py -q
```

预期：

- FAIL，字段不全或提取条件不对

**步骤 3：编写最小实现**

实现内容：

- 在 `dxf_service.py` 增加候选块识别函数
- 统一构造 `detail_titles`
- 在 `layout_json_service.py` 的回填链路中写入该字段
- 保持现有 `indexes`、`title_blocks` 输出不变

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_dxf_service.py tests/test_layout_json_service.py -q
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/dxf_service.py cad-review-backend/services/layout_json_service.py cad-review-backend/tests/test_dxf_service.py cad-review-backend/tests/test_layout_json_service.py
git commit -m "feat: extract detail titles from dxf blocks"
```

### 任务 3：重构索引审核命中逻辑为统一引用集合

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_issue_preview_api.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dxf_service.py`

**步骤 1：编写失败的测试**

新增回归用例：

- 目标图 `G0.04` 没有 `indexes`
- 但有 `detail_titles.label = A1`
- 审核 `G0.03 -> G0.04 / A1` 时不应再报“目标图未找到同编号索引”

再补一条：

- 若 `detail_titles` 也没有对应编号，则仍然报错

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_issue_preview_api.py tests/test_dxf_service.py -q
```

预期：

- FAIL，当前审核逻辑仍把这类情况判成缺失

**步骤 3：编写最小实现**

实现内容：

- 在 `index_audit.py` 中新增统一引用标签构建函数
- 合并：
  - `indexes`
  - `title_blocks.title_label`
  - `detail_titles.label`
- 审核证据中写入命中的实体来源，例如：
  - `matched_target_entity_type = detail_title`
  - `matched_target_block_name`

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_issue_preview_api.py tests/test_dxf_service.py -q
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit/index_audit.py cad-review-backend/tests/test_issue_preview_api.py cad-review-backend/tests/test_dxf_service.py
git commit -m "feat: use semantic reference labels in index audit"
```

### 任务 4：对真实项目做旧数据补齐并验证 `G0.03 -> G0.04 / A1`

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/utils/backfill_layout_jsons.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_layout_json_service.py`

**步骤 1：编写失败的测试**

新增测试：

- 当旧 JSON 缺少 `detail_titles` 时，backfill 能补齐
- 不会破坏已有 `indexes`、`title_blocks`、`symbol_bbox`

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_layout_json_service.py -q
```

预期：

- FAIL，回填缺少 `detail_titles`

**步骤 3：编写最小实现**

实现内容：

- `backfill_layout_jsons.py` 读取最新提取逻辑
- 对当前项目执行一次旧数据补齐
- 记录 `processed/updated/missing`

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_layout_json_service.py -q
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/python utils/backfill_layout_jsons.py --project-id proj_20260305110134428994 --latest-only
```

预期：

- 测试 PASS
- 项目回填输出 `updated > 0`

**步骤 5：提交**

```bash
git add cad-review-backend/utils/backfill_layout_jsons.py cad-review-backend/tests/test_layout_json_service.py
git commit -m "feat: backfill semantic detail titles in legacy jsons"
```

### 任务 5：预留 AI 兜底接口，不接入主链路

**文件：**
- 新建：`/Users/harry/@dev/ccad/docs/plans/2026-03-08-index-ai-fallback-notes.md`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py`

**步骤 1：编写失败的测试**

这一任务不强制先写自动化测试，主要目的是明确扩展点，不让主链路耦死。

可补一个轻量单测：

- 当规则未命中但存在候选对象时，返回 `needs_ai_fallback = true`

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_issue_preview_api.py -q
```

预期：

- FAIL，当前没有该扩展点字段

**步骤 3：编写最小实现**

实现内容：

- 在审核结果内部保留一个不影响现网行为的扩展位：
  - `needs_ai_fallback`
  - `ai_fallback_reason`
- 文档中记录未来 AI 的触发条件和输入输出约束
- 本轮不真正接 AI

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_issue_preview_api.py -q
```

预期：

- PASS

**步骤 5：提交**

```bash
git add docs/plans/2026-03-08-index-ai-fallback-notes.md cad-review-backend/services/audit/index_audit.py
git commit -m "chore: reserve ai fallback hooks for index audit"
```

### 任务 6：全链路回归验证

**文件：**
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_issue_preview_api.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dxf_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_layout_json_service.py`

**步骤 1：补最终回归清单**

回归场景至少覆盖：

1. 标准 `indexes` 仍命中
2. `title_blocks.title_label` 仍命中
3. `detail_titles.label` 新增命中
4. 无任何命中时仍报错
5. `G0.03 -> G0.04 / A1` 不再误报

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_dxf_service.py tests/test_layout_json_service.py tests/test_issue_preview_api.py -q
```

预期：

- 若前面实现不完整，至少一条 FAIL

**步骤 3：补齐最小实现和回归断言**

确保所有断言都围绕“统一语义层”而不是单案例特判。

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_dxf_service.py tests/test_layout_json_service.py tests/test_issue_preview_api.py tests/test_coordinate_service.py tests/test_registration_service.py tests/test_drawing_annotations_api.py tests/test_audit_feedback_api.py tests/test_skill_pack_injection.py -q
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/tests/test_dxf_service.py cad-review-backend/tests/test_layout_json_service.py cad-review-backend/tests/test_issue_preview_api.py
git commit -m "test: lock semantic index audit regressions"
```

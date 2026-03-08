# 图框优先的多图布局切分实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 为 DWG 提取链路新增“图框优先的 layout 内分图”能力，让一个 layout 中的多张图纸能被切分成独立 fragment，并正确参与目录匹配、上下文构建和审图任务规划。

**架构：** 在 DXF 提取阶段先识别图框和多图 layout，再生成 fragment 级 JSON；目录匹配、三线匹配、上下文构建和任务规划全部下沉到 fragment 维度。单图 layout 保持现有兼容路径，避免影响 `test1/test4` 这类已正常项目。

**技术栈：** FastAPI、SQLAlchemy、Python、pytest、DWG/DXF、ezdxf、React、TypeScript

---

### 任务 1：为图框识别和多图 layout 检测补测试

**文件：**
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dxf_service.py`

**步骤 1：编写失败的测试**

新增测试覆盖：

- `test_detects_single_frame_layout`
- `test_detects_multi_sheet_layout_when_multiple_frames_exist`
- `test_frame_detection_prefers_outer_drawing_border_over_inner_geometry`

至少断言：

- 能识别 `frame_bbox`
- 能输出 `paper_size_hint`
- 能输出 `orientation`
- 能标记 `multi_sheet_layout`

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_dxf_service.py -q
```

预期：

- FAIL，提示不存在 frame 检测结果

**步骤 3：编写最小实现**

在 `dxf_service.py` 中新增图框候选识别逻辑：

- 扫描大矩形 / 封闭 polyline
- 结合边界位置、长宽比和标题栏区域打分
- 生成 `layout_frames`

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_dxf_service.py -q
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/tests/test_dxf_service.py cad-review-backend/services/dxf_service.py
git commit -m "feat: detect drawing frames in layout extraction"
```

### 任务 2：在提取结果中引入 `layout_frames` 和 `layout_fragments`

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/dxf_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/cad_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dxf_service.py`

**步骤 1：编写失败的测试**

新增测试：

- 单图 layout 输出 `layout_frames=1`、`layout_fragments=1`
- 多图 layout 输出多个 fragment
- 每个 fragment 都带：
  - `frame_id`
  - `bbox`
  - `sheet_no`
  - `sheet_name`
  - `scale`

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_dxf_service.py -q
```

预期：

- FAIL，当前提取结果仍只有单 layout 输出

**步骤 3：编写最小实现**

实现内容：

- 在 layout 内先识别 `layout_frames`
- 在每个 frame 内收集标题块、详图标题、viewport 和语义对象
- 生成 `layout_fragments`
- 保留父级 layout 元数据，兼容单图路径

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_dxf_service.py -q
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/dxf_service.py cad-review-backend/services/cad_service.py cad-review-backend/tests/test_dxf_service.py
git commit -m "feat: emit frame-based layout fragments"
```

### 任务 3：将 JSON 输出从 layout-level 扩展到 fragment-level

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/dxf_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/layout_json_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_layout_json_service.py`

**步骤 1：编写失败的测试**

新增测试：

- 多图 layout 会写出多个 fragment JSON
- JSON 命名中包含 fragment 标识
- JSON 中保留：
  - `parent_layout_name`
  - `frame_bbox`
  - `fragment_bbox`
  - `is_multi_sheet_layout`

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_layout_json_service.py -q
```

预期：

- FAIL，当前 JSON 仍是一 layout 一文件

**步骤 3：编写最小实现**

实现内容：

- 单图 layout 继续兼容原文件结构
- 多图 layout 输出多个 fragment 文件
- 回填逻辑能识别 fragment JSON，不误判成 placeholder

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_layout_json_service.py -q
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/layout_json_service.py cad-review-backend/tests/test_layout_json_service.py cad-review-backend/services/dxf_service.py
git commit -m "feat: persist fragment-level layout json"
```

### 任务 4：把目录匹配从 layout 维度改到 fragment 维度

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/dwg.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/drawing_ingest/dwg_ingest_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_match_scoring.py`

**步骤 1：编写失败的测试**

新增测试：

- 一个 layout 里的两个 fragment 能匹配两个不同目录项
- `sheet_no=""` 但标题块清晰的 fragment 能命中目录
- 不能把一个多图 layout 整体只匹配到一个目录项

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_match_scoring.py -q
```

预期：

- FAIL，当前匹配仍是一 layout 一目录

**步骤 3：编写最小实现**

实现内容：

- `upload_dwg` 和 ingest 服务改为消费 fragment 列表
- `catalog_id` 绑定到 fragment，而不是父 layout
- placeholder 只在 fragment 级别确实缺数据时生成

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_match_scoring.py -q
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/routers/dwg.py cad-review-backend/services/drawing_ingest/dwg_ingest_service.py cad-review-backend/tests/test_match_scoring.py
git commit -m "feat: match catalogs against extracted fragments"
```

### 任务 5：按 fragment 重建三线匹配和图纸上下文

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/context_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_start_audit_api.py`

**步骤 1：编写失败的测试**

新增测试：

- 多图 layout 项目能构建多个 `SheetContext`
- 其中 ready fragment 能生成上下文
- 三线匹配 summary 不再因为父 layout 混淆而退化

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_start_audit_api.py -q
```

预期：

- FAIL，当前上下文仍基于旧 layout JSON

**步骤 3：编写最小实现**

实现内容：

- `match_three_lines` 基于 fragment 资产计算
- `build_sheet_contexts` 从 fragment JSON 读取 `frame_bbox / fragment_bbox`
- 只对 ready fragment 建上下文

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_start_audit_api.py tests/test_issue_preview_api.py -q
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_service.py cad-review-backend/services/context_service.py cad-review-backend/tests/test_start_audit_api.py cad-review-backend/tests/test_issue_preview_api.py
git commit -m "feat: build sheet contexts from fragments"
```

### 任务 6：按 fragment 重建审图任务规划

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/task_planner_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_skill_pack_injection.py`

**步骤 1：编写失败的测试**

新增测试：

- 对多图 layout 项目，任务规划不再返回空任务图
- 当 fragment 中存在索引、尺寸或材料语义时，能生成对应任务

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_skill_pack_injection.py -q
```

预期：

- FAIL，当前 planner 仍按旧上下文推任务

**步骤 3：编写最小实现**

实现内容：

- `task_planner_service` 不再依赖“一个 layout 一个上下文”
- fragment 上的索引关系可以生成 `SheetEdge`
- 多图 layout 项目能产出非空任务图

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_skill_pack_injection.py tests/test_master_planner_service.py -q
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/task_planner_service.py cad-review-backend/services/audit_runtime_service.py cad-review-backend/tests/test_skill_pack_injection.py cad-review-backend/tests/test_master_planner_service.py
git commit -m "feat: plan audit tasks from frame-based fragments"
```

### 任务 7：引入图框坐标系并兼容预览定位

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/coordinate_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/registration_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/issue_preview.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_coordinate_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_registration_service.py`

**步骤 1：编写失败的测试**

新增测试：

- `frame_bbox` 存在时，优先生成 `frame_local_pct`
- 多图 layout 中的索引点不会跨图漂移到另一个 fragment

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_coordinate_service.py tests/test_registration_service.py -q
```

预期：

- FAIL，当前坐标仍按整 layout 或整页计算

**步骤 3：编写最小实现**

实现内容：

- `coordinate_service` 新增 frame 坐标系归一化
- `issue_preview` 和 registration 优先消费 fragment/frame 坐标

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_coordinate_service.py tests/test_registration_service.py tests/test_issue_preview_api.py -q
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/coordinate_service.py cad-review-backend/services/registration_service.py cad-review-backend/services/audit/issue_preview.py cad-review-backend/tests/test_coordinate_service.py cad-review-backend/tests/test_registration_service.py cad-review-backend/tests/test_issue_preview_api.py
git commit -m "feat: normalize issue anchors by detected drawing frame"
```

### 任务 8：用 `test1/test2/test3/test4` 做真实回归验证

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/utils/test_autocad_com_extract.py`
- 文档：`/Users/harry/@dev/ccad/docs/plans/2026-03-08-frame-first-multi-sheet-layout-design.md`

**步骤 1：编写验证脚本增强**

增强脚本输出：

- 每套 DWG 的 fragment 数
- `sheet_no_empty`
- `placeholder_count`
- `indexes / dimensions / materials / title_blocks`

**步骤 2：运行真实验证**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/python utils/test_autocad_com_extract.py --dwg-dir /Users/harry/@dev/ccad/test-files/test2_cad-企业展厅施工图 --out-dir /tmp/ccad-test-extract/test2
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/python utils/test_autocad_com_extract.py --dwg-dir /Users/harry/@dev/ccad/test-files/test3_cad-宁波天誉展厅施工图 --out-dir /tmp/ccad-test-extract/test3
```

预期：

- `test1/test4` 不回退
- `test2/test3` 的 `sheet_no_empty` 明显下降
- 多图 layout 能产生多个 fragment

**步骤 3：记录结果**

把真实回归结果补进设计文档或实现说明中，方便后续追踪。

**步骤 4：提交**

```bash
git add cad-review-backend/utils/test_autocad_com_extract.py docs/plans/2026-03-08-frame-first-multi-sheet-layout-design.md
git commit -m "docs: record frame-first fragment extraction validation"
```

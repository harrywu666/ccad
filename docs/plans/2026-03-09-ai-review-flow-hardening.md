# AI 审图流程加固实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 修正 AI 审图主链路里的状态污染、提示词未生效、预规划与正式执行不一致、缓存复用不足、旧实现并存等问题，让“配置可调、流程可复现、结果可回归”。

**架构：** 以当前运行时主链路为准，优先修复 `orchestrator -> relationship_discovery -> task_planner -> audit/*` 之间的状态与配置一致性问题，再处理缓存键和旧实现收口。所有改动坚持 TDD：先补回归测试，再做最小实现，最后运行目标测试集验证。

**技术栈：** FastAPI、SQLAlchemy、SQLite、React 19、Vite、pytest、httpx

---

## 决策点

### 决策点 A：`/audit/tasks/plan` 是否必须与正式 `start_audit` 完全同构

**推荐：** 是。让它默认执行“构建上下文 + AI 关系发现 + 任务规划”，产出的任务图与正式审图保持一致。

**备选：** 保持轻量预规划，只做上下文和规则/LLM 规划，但前端与接口文档必须明确标注“非正式结果，不含 AI 关系发现”。

### 决策点 B：旧 `audit_service.py` 的 dimension/material 实现采用软废弃还是直接删除

**推荐：** 先软废弃一轮。保留 `match_three_lines()`，把旧 `audit_dimensions()` / `audit_materials()` 标注为 deprecated，并移出主维护面；待验证新链路稳定后再删除。

**备选：** 直接删除旧实现，同时补齐替代模块的测试覆盖。

### 决策点 C：尺寸缓存是否允许跨 `audit_version` 复用

**推荐：** 允许。缓存键以“输入内容哈希”为准，而不是审图版本号。

**备选：** 不允许。继续以版本隔离缓存，但要明确接受重复审图的额外成本。

---

### 任务 1：修复 AI 关系边的陈旧状态污染

**文件：**
- 新建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_relationship_discovery.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`

**步骤 1：编写失败的测试**

在 `test_relationship_discovery.py` 中新增场景：

- 先插入一条 `edge_type="ai_visual"` 的旧边
- 调用 `save_ai_edges(project_id, [], db)`
- 预期数据库中该项目的 `ai_visual` 边数量为 `0`

最小测试骨架：

```python
def test_save_ai_edges_clears_stale_rows_when_new_result_is_empty():
    save_ai_edges("proj-1", [], db)
    rows = db.query(models.SheetEdge).filter(
        models.SheetEdge.project_id == "proj-1",
        models.SheetEdge.edge_type == "ai_visual",
    ).all()
    assert rows == []
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_relationship_discovery.py
```

预期：

- FAIL，旧边仍存在

**步骤 3：编写最小实现**

实现内容：

- 调整 `save_ai_edges()` 的事务边界
- 无论新结果是否为空，都提交删除动作
- 若有新增边，保持同一事务内写入并提交

建议实现骨架：

```python
db.query(SheetEdge).filter(
    SheetEdge.project_id == project_id,
    SheetEdge.edge_type == "ai_visual",
).delete(synchronize_session=False)

for rel in relationships:
    db.add(SheetEdge(...))

db.commit()
```

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_relationship_discovery.py
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit/relationship_discovery.py cad-review-backend/tests/test_relationship_discovery.py
git commit -m "fix: clear stale ai relationship edges"
```

### 任务 2：让图纸关系发现真正接入可配置提示词

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/ai_prompt_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_relationship_discovery.py`

**步骤 1：编写失败的测试**

新增两个场景：

- `resolve_stage_prompts("sheet_relationship_discovery", {"discovery_prompt": "X"})` 的 `user_prompt` 被真正传给 `call_kimi`
- 覆盖数据库中的 `sheet_relationship_discovery.user_prompt` 后，运行时收到覆盖后的文本

最小测试骨架：

```python
async def fake_call_kimi(**kwargs):
    captured["user_prompt"] = kwargs["user_prompt"]
    return []

assert "自定义关系发现提示词" in captured["user_prompt"]
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_relationship_discovery.py
```

预期：

- FAIL，当前 user prompt 仍来自 `_build_discovery_prompt()` 的硬编码文本

**步骤 3：编写最小实现**

实现内容：

- 保留 `_build_discovery_prompt()` 作为变量构造器，只负责拼 `discovery_prompt`
- 在 `_discover_group()` 中改为：

```python
prompts = resolve_stage_prompts(
    "sheet_relationship_discovery",
    {"discovery_prompt": _build_discovery_prompt(group_sheets, all_catalog_entries)},
)
result = await call_kimi(
    system_prompt=resolve_stage_system_prompt_with_skills(...),
    user_prompt=prompts["user_prompt"],
    images=all_images,
    temperature=0.0,
)
```

- 如需避免 system prompt 配置与技能包拼接冲突，可新增“先 resolve，再拼技能规则”的辅助函数；不要让同一阶段出现两套拼接方式

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_relationship_discovery.py tests/test_skill_pack_injection.py
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit/relationship_discovery.py cad-review-backend/services/ai_prompt_service.py cad-review-backend/tests/test_relationship_discovery.py
git commit -m "feat: route relationship discovery through prompt settings"
```

### 任务 3：统一手动预规划接口与正式审图链路

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 视实现选择修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 新建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_plan_audit_tasks_api.py`

**步骤 1：编写失败的测试**

新增接口场景：

- 调用 `POST /api/projects/{project_id}/audit/tasks/plan`
- mock `discover_relationships()` 返回一条 `A1.01 -> A4.01`
- 预期 `build_audit_tasks()` 看到该 AI 边，最终任务摘要包含相应 `dimension/material` 任务

最小测试骨架：

```python
def test_plan_audit_tasks_runs_ai_relationship_discovery(client, monkeypatch):
    monkeypatch.setattr(relationship_discovery, "discover_relationships", lambda *_: [...])
    response = client.post("/api/projects/proj-1/audit/tasks/plan")
    assert response.status_code == 200
    assert response.json()["task_summary"]["dimension_tasks"] >= 1
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_plan_audit_tasks_api.py
```

预期：

- FAIL，当前接口不执行 AI 关系发现

**步骤 3：编写最小实现**

若采用“完全同构”方案：

- 在 `plan_audit_tasks()` 中加入 `discover_relationships()` + `save_ai_edges()`
- 返回值中追加 `relationship_summary`
- 与 `start_audit` 保持相同阶段顺序：上下文 -> AI 关系 -> 任务规划

若采用“轻量预规划”方案：

- 保持现状
- 但接口返回字段中显式加 `scope_mode: "preview_without_ai_relationships"`
- 前端文案同步修改，避免误导

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_plan_audit_tasks_api.py tests/test_start_audit_api.py
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/routers/audit.py cad-review-backend/services/audit_runtime/orchestrator.py cad-review-backend/tests/test_plan_audit_tasks_api.py
git commit -m "feat: align manual audit planning with runtime pipeline"
```

### 任务 4：重构尺寸审核缓存键，支持真正的输入级复用

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 新建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dimension_audit_cache.py`

**步骤 1：编写失败的测试**

新增场景：

- 相同 PDF、相同 JSON 尺寸数据、相同 prompt、不同 `audit_version`
- 生成的 sheet semantic cache key 相同
- 生成的 pair compare cache key 相同

最小测试骨架：

```python
def test_sheet_cache_key_does_not_change_only_because_audit_version_changes():
    key_v1 = build_sheet_cache_key(..., audit_version=1)
    key_v2 = build_sheet_cache_key(..., audit_version=2)
    assert key_v1 == key_v2
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_dimension_audit_cache.py
```

预期：

- FAIL，当前 cache key 包含 `audit_version`

**步骤 3：编写最小实现**

实现内容：

- 抽出缓存键构造函数，避免散落在流程函数内部
- cache key 只依赖：
  - `prompt_version`
  - 渲染后的 prompt/system prompt 哈希
  - `pdf_path/page_index/file_sig`
  - `dims_compact` 或 semantic hash
  - `visual_only` 标识
- 从 key 中移除 `audit_version`

建议抽出的函数：

```python
def _sheet_semantic_cache_key(...): ...
def _pair_compare_cache_key(...): ...
```

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_dimension_audit_cache.py tests/test_skill_pack_injection.py
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit/dimension_audit.py cad-review-backend/tests/test_dimension_audit_cache.py
git commit -m "refactor: make dimension cache keys input based"
```

### 任务 5：收口旧 `audit_service.py` 的 dimension/material 实现

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/__init__.py`
- 可选新增：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_service_deprecation.py`

**步骤 1：编写失败的测试**

按“软废弃”方案新增场景：

- 调用旧 `audit_service.audit_dimensions()` 时抛出明确异常，提示改用 `services.audit.dimension_audit.audit_dimensions`
- `match_three_lines()` 行为保持不变

最小测试骨架：

```python
with pytest.raises(RuntimeError, match="deprecated"):
    audit_service.audit_dimensions("proj-1", 1, db)
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_audit_service_deprecation.py
```

预期：

- FAIL，当前旧实现仍可直接运行

**步骤 3：编写最小实现**

软废弃方案：

- 保留 `match_three_lines()`
- 将旧 `audit_dimensions()` / `audit_materials()` 替换为显式异常：

```python
raise RuntimeError(
    "services.audit_service.audit_dimensions 已废弃，请改用 services.audit.dimension_audit.audit_dimensions"
)
```

直接删除方案：

- 删除旧实现
- 修正所有引用与导出
- 确保没有遗留入口依赖

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_audit_service_deprecation.py tests/test_start_audit_api.py
```

预期：

- PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_service.py cad-review-backend/services/audit/__init__.py cad-review-backend/tests/test_audit_service_deprecation.py
git commit -m "refactor: deprecate legacy audit service entrypoints"
```

### 任务 6：回归验证与人工验收

**文件：**
- 修改：`/Users/harry/@dev/ccad/docs/plans/2026-03-09-ai-review-flow-hardening.md`
- 可选记录：`/Users/harry/@dev/ccad/cad-review-backend/tests/run_full_e2e.py`

**步骤 1：运行后端目标测试集**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q \
  tests/test_master_planner_service.py \
  tests/test_skill_pack_injection.py \
  tests/test_start_audit_api.py \
  tests/test_relationship_discovery.py \
  tests/test_plan_audit_tasks_api.py \
  tests/test_dimension_audit_cache.py \
  tests/test_audit_service_deprecation.py
```

预期：

- PASS

**步骤 2：执行一轮人工链路验收**

验收清单：

- 设置页修改 `sheet_relationship_discovery` 提示词后，运行时日志和结果确实变化
- `POST /audit/tasks/plan` 与正式 `POST /audit/start` 的任务图一致
- 当 AI 关系发现为空时，不会继承上一轮 `ai_visual` 边
- 连续两次相同输入审图，第二次命中尺寸缓存

**步骤 3：补充计划备注与风险清单**

在本计划文档末尾追加：

- 本轮采用的决策点结论
- 未完成项
- 后续可删的 deprecated 代码入口

**步骤 4：提交**

```bash
git add docs/plans/2026-03-09-ai-review-flow-hardening.md
git commit -m "docs: finalize ai review flow hardening plan"
```

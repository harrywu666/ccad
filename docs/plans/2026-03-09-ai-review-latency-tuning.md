# AI 审图延迟调优实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 让 AI 审图在真实大项目上更容易拿到关系发现和总控规划结果，同时保留可控的超时与降级行为。

**架构：** 通过两条线并行收口：一条提升默认超时上限，让真实 Kimi 结果有机会返回；另一条降低关系发现的单次调用成本，包括更小批次和更轻的渲染配置。所有改动以环境变量参数化，并通过回归测试固定行为。

**技术栈：** FastAPI、SQLAlchemy、pytest、httpx、PyMuPDF/Pillow

---

### 任务 1：关系发现批次与渲染参数收口

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/image_pipeline.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_relationship_discovery.py`

**步骤：**
1. 编写失败测试，覆盖 group size 环境变量和更小批次分组。
2. 在关系发现服务中引入环境变量控制的 `group_size`、`concurrency`、`render_max_width`、`full_dpi`、`detail_dpi`。
3. 让关系发现调用使用更轻量的渲染参数，但不影响尺寸/材料审核默认渲染配置。
4. 运行关系发现相关测试，确认超时和新批次逻辑都保持稳定。

### 任务 2：总控规划默认超时调优

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/master_planner_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_master_planner_service.py`

**步骤：**
1. 保留显式环境变量优先级，提升默认超时到更适合真实项目的级别。
2. 确认现有显式超时测试仍然可稳定触发 `llm_timeout`。
3. 运行 master planner 相关测试验证没有行为回归。

### 任务 3：真实链路复验

**文件：**
- 使用：`/Users/harry/@dev/ccad/cad-review-backend/utils/manual_check_ai_review_flow.py`

**步骤：**
1. 重启 7002 服务并注入当前有效 `KIMI_CODE_API_KEY`。
2. 顺序运行真实 `/audit/tasks/plan` 和人工验收脚本，避免 SQLite 并发写锁干扰。
3. 记录实际返回的 `relationship_summary`、`planner_reason`、任务数量，并保存报告。

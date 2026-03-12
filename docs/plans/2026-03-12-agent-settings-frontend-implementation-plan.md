# Agent设置前端重构 实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 把设置页从“提示词设置”改成“Agent设置”，主视角直接管理各个 Agent 的 md 文件，并把旧 stage prompt 收到兼容层里。

**架构：** 前端新增 Agent 视角的设置页，按 Agent 分块展示 `AGENTS.md / SOUL.md / MEMORY.md` 和 `SKILL.md`。后端只补最小接口，让 `review_worker` 下的 skill 文件可读可写，不改审图主流程。

**技术栈：** React 19、Vite、Vitest、FastAPI、pytest

---

### 任务 1：补 review_worker skill 文件接口

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/review_worker_skill_asset_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/settings.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_review_worker_skill_asset_settings_api.py`

### 任务 2：前端接通 Agent 文件和 Worker Skills 数据

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/api/index.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/types/api.ts`

### 任务 3：重构设置页主视角

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/SettingsPage.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/settings/SettingsPrompts.tsx`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/settings/SettingsLegacyStagePrompts.tsx`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/settings/SettingsReviewWorkerSkills.tsx`

### 任务 4：补最小前端回归

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/settings/__tests__/SettingsPrompts.test.tsx`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/settings/__tests__/SettingsReviewWorkerSkills.test.tsx`

### 任务 5：验证

**步骤：**
- 跑后端新增接口测试
- 跑前端设置页相关测试
- 必要时跑一次前端构建或最小语法检查

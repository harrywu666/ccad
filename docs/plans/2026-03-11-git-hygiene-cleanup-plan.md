# Git Hygiene Cleanup 实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 把 `ccad` 仓库从“运行产物和源码混在一起”的状态，整理为“源码可追踪、本地输出可忽略、分支用途清晰”的状态。

**架构：** 不改写历史，先做工作区级整理，再逐步把已被 Git 跟踪的运行文件从索引中移除。整个过程分成小步执行，每一步都能单独验证和回退，避免一次性清空几千个文件导致误删。

**技术栈：** Git、`.gitignore`、worktree、本地运行目录、Python/Node 项目结构

---

### 任务 1：冻结当前状态并创建安全锚点

**文件：**
- 修改：无
- 记录：`docs/plans/2026-03-11-git-hygiene-cleanup-plan.md`

**步骤 1：检查当前状态**

运行：`git status --short --branch`
预期：看到 `main` 上仍有大量修改和未跟踪文件。

**步骤 2：创建备份分支**

运行：`git branch backup/pre-git-hygiene-2026-03-11`
预期：生成一个本地备份分支，指向当前 `main`。

**步骤 3：确认备份分支存在**

运行：`git branch --list 'backup/pre-git-hygiene-2026-03-11'`
预期：输出备份分支名称。

### 任务 2：只保留源码，移除索引中的运行产物

**文件：**
- 修改：`.gitignore`

**步骤 1：确认已忽略目录**

运行：`git check-ignore -v .run cad-review-backend/.run codex-bridge/node_modules`
预期：输出对应的 `.gitignore` 规则来源。

**步骤 2：从 Git 索引中移除运行目录，但保留本地文件**

运行：

```bash
git rm -r --cached .run .artifacts cad-review-backend/venv
git rm -r --cached -- 'cad-review-backend/**/__pycache__'
git rm --cached cad-review-backend/.env
```

预期：这些文件从“已跟踪”变成“已删除待提交”，但磁盘上的文件仍保留。

**步骤 3：验证运行产物不再被跟踪**

运行：`git ls-files | rg '(^|/)(\\.run/|\\.artifacts/|venv/|__pycache__/|\\.env$)'`
预期：输出显著减少，理想情况下只剩真正需要版本管理的文件。

**步骤 4：提交清理**

运行：

```bash
git add .gitignore
git commit -m "chore: stop tracking local runtime artifacts"
```

预期：形成单独的“仓库卫生”提交。

### 任务 3：整理 `main` 上的业务改动

**文件：**
- 修改：本次真实开发相关源码和测试文件

**步骤 1：查看清理后还剩哪些改动**

运行：`git status --short`
预期：主要剩源码、测试、文档变更。

**步骤 2：把业务改动按主题拆到分支**

运行：

```bash
git switch -c feat/<topic-name>
git add <real-source-files>
git commit -m "feat: <topic summary>"
```

预期：`main` 回到更干净状态，业务改动在功能分支上。

**步骤 3：验证分支差异**

运行：`git diff --stat main...HEAD`
预期：只看到当前主题相关文件。

### 任务 4：梳理分支生命周期

**文件：**
- 修改：无

**步骤 1：查看已合并分支**

运行：`git branch --merged main`
预期：列出已经完全落到 `main` 的分支。

**步骤 2：删除不再需要的已合并分支**

运行：

```bash
git branch -d codex/drawing-annotations
```

预期：删除本地已合并且不再活跃的分支。

**步骤 3：保留有 worktree 的活跃分支**

运行：`git worktree list`
预期：看到 `codex/audit-workbench-electron` 仍被 worktree 使用，不删除。

### 任务 5：建立以后不再混乱的最小规则

**文件：**
- 修改：`AGENTS.md`（如果需要补项目规则）
- 修改：`.gitignore`

**步骤 1：约定主分支只做两件事**

规则：
- `main` 只保留可提交、可推送的内容
- 实验、调试、E2E 输出一律放功能分支或 worktree

**步骤 2：每次开发前先建分支**

运行：`git switch -c feat/<short-topic>`
预期：新需求不再直接堆在 `main`。

**步骤 3：每次推送前只看这三个命令**

运行：

```bash
git status --short --branch
git branch -vv
git branch --merged main
```

预期：快速确认当前分支、是否干净、哪些分支已可删除。

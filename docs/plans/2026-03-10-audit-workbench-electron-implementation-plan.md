# 审图桌面工作台（Electron）实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 在不移除现有 Web 页面前提下，为审图系统新增一个 Electron 桌面壳和一套新的“审图工作台”界面，让用户能在桌面版里完成从项目、上传、图纸管理到审图和报告的整条主流程。

**架构：** 继续复用现有 `Vite + React` 前端，新增 `Electron` 主进程与预加载层。前端新增一个独立的工作台路由 `/projects/:id/workbench`，采用“三栏工作区”布局：左栏会话、中央主工作区、右栏过程流。第一阶段先以现有 API 和现有状态接口为基础，不改变后端协议，只重组前端形态与桌面壳。

**技术栈：** Electron、Vite、React、TypeScript、React Router、现有前端组件库、Playwright、Vitest（或当前前端测试方式）。

---

### 任务 1：先把 Electron 桌面壳立起来

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/package.json`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/electron/main.cjs`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/electron/preload.cjs`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/electron-builder.yml`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/scripts/build-electron.mjs`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/test/electron-shell.smoke.test.ts`

**步骤 1：编写失败的测试**

```ts
import { existsSync } from 'node:fs'

it('has electron entry files', () => {
  expect(existsSync('/Users/harry/@dev/ccad/cad-review-frontend/electron/main.cjs')).toBe(true)
  expect(existsSync('/Users/harry/@dev/ccad/cad-review-frontend/electron/preload.cjs')).toBe(true)
})
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/electron-shell.smoke.test.ts
```

预期：FAIL，提示 electron 入口文件不存在。

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add src/test/electron-shell.smoke.test.ts
git commit -m "test: add failing electron shell smoke test"
```

**步骤 4：实现最小桌面壳**

要求：

- 开发模式支持 `vite dev + electron`
- 生产模式支持打包渲染进程再启动 Electron
- 主窗口默认宽屏
- 关闭时不强行退出后台后端
- 预加载层先暴露最小 `desktopShell` 标记

建议最小主进程结构：

```js
const { app, BrowserWindow } = require('electron')
const path = require('path')

function createWindow() {
  const win = new BrowserWindow({
    width: 1540,
    height: 980,
    minWidth: 1280,
    minHeight: 820,
    titleBarStyle: 'hiddenInset',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  const url = process.env.ELECTRON_RENDERER_URL || `file://${path.join(__dirname, '../dist/index.html')}`
  win.loadURL(url)
}
```

**步骤 5：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/electron-shell.smoke.test.ts
```

预期：PASS

**步骤 6：补启动验证**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm run electron:dev
```

预期：桌面窗口能打开，首页能显示项目列表。

**步骤 7：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add package.json electron scripts src/test/electron-shell.smoke.test.ts electron-builder.yml
git commit -m "feat: add electron desktop shell"
```

---

### 任务 2：给前端加新的工作台路由，不替换旧详情页

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/App.tsx`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench.tsx`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/test/auditWorkbenchRoute.test.tsx`

**步骤 1：编写失败的测试**

```tsx
it('registers workbench route', () => {
  // 渲染 App 后，/projects/123/workbench 应该命中新页面
})
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/auditWorkbenchRoute.test.tsx
```

预期：FAIL，提示路由不存在。

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add src/test/auditWorkbenchRoute.test.tsx
git commit -m "test: add failing audit workbench route test"
```

**步骤 4：实现最小新路由**

要求：

- 保留：
  - `/`
  - `/projects/:id`
  - `/settings`
- 新增：
  - `/projects/:id/workbench`
- 新页面先输出明确标题：`审图工作台`

**步骤 5：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/auditWorkbenchRoute.test.tsx
```

预期：PASS

**步骤 6：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add src/App.tsx src/pages/AuditWorkbench.tsx src/test/auditWorkbenchRoute.test.tsx
git commit -m "feat: add audit workbench route"
```

---

### 任务 3：先搭三栏工作台骨架

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench/components/WorkbenchShell.tsx`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench/components/WorkbenchSidebar.tsx`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench/components/WorkbenchMain.tsx`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench/components/WorkbenchInspector.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench.tsx`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/test/workbenchLayout.test.tsx`

**步骤 1：编写失败的测试**

```tsx
it('renders sidebar main and inspector columns', () => {
  // 应能找到三个区域标记
})
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/workbenchLayout.test.tsx
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add src/test/workbenchLayout.test.tsx
git commit -m "test: add failing workbench layout test"
```

**步骤 4：实现三栏骨架**

要求：

- 左栏固定宽度，显示会话列表区
- 中栏自适应，作为主工作区
- 右栏固定宽度，显示过程与细节
- 顶部像桌面工具栏，不再像普通网页页头

**步骤 5：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/workbenchLayout.test.tsx
```

预期：PASS

**步骤 6：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add src/pages/AuditWorkbench.tsx src/pages/AuditWorkbench/components src/test/workbenchLayout.test.tsx
git commit -m "feat: add audit workbench three-pane layout"
```

---

### 任务 4：把左栏做成“审图会话优先”，不是普通项目菜单

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench/hooks/useAuditSessions.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench/components/WorkbenchSidebar.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/api/index.ts`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/test/workbenchSidebar.test.tsx`

**步骤 1：编写失败的测试**

```tsx
it('shows audit sessions as the primary list', () => {
  // 左栏主列表应显示会话状态和更新时间
})
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/workbenchSidebar.test.tsx
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add src/test/workbenchSidebar.test.tsx
git commit -m "test: add failing workbench sidebar session test"
```

**步骤 4：实现左栏内容**

要求：

- 主列表是审图会话
- 每条显示：
  - 会话状态
  - 项目名
  - 版本号或轮次
  - 最近更新时间
- 顶部保留项目切换和新建入口

如果后端暂时没有单独会话接口，第一版可用：
- `auditHistory`
- `auditStatus`
- 当前项目数据

先拼出工作台会话列表。

**步骤 5：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/workbenchSidebar.test.tsx
```

预期：PASS

**步骤 6：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add src/pages/AuditWorkbench/hooks/useAuditSessions.ts src/pages/AuditWorkbench/components/WorkbenchSidebar.tsx src/api/index.ts src/test/workbenchSidebar.test.tsx
git commit -m "feat: add session-first workbench sidebar"
```

---

### 任务 5：把中栏主工作区拆成五个视图

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench/components/views/OverviewView.tsx`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench/components/views/CatalogView.tsx`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench/components/views/DrawingsView.tsx`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench/components/views/AuditRunView.tsx`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench/components/views/ReportView.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench/components/WorkbenchMain.tsx`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/test/workbenchViews.test.tsx`

**步骤 1：编写失败的测试**

```tsx
it('switches between overview catalog drawings audit and report views', () => {
  // 点击不同标签后，应切换主工作区内容
})
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/workbenchViews.test.tsx
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add src/test/workbenchViews.test.tsx
git commit -m "test: add failing workbench views test"
```

**步骤 4：实现五个主视图**

要求：

- `总览`
- `目录`
- `图纸`
- `审图`
- `报告`

第一版优先复用现有组件：

- 目录表格
- 匹配表格
- 报告列表
- Finding 状态

不要重复造轮子。

**步骤 5：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/workbenchViews.test.tsx
```

预期：PASS

**步骤 6：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add src/pages/AuditWorkbench/components/views src/pages/AuditWorkbench/components/WorkbenchMain.tsx src/test/workbenchViews.test.tsx
git commit -m "feat: add workbench main views"
```

---

### 任务 6：把右栏做成常驻过程区，不再依赖弹窗

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench/components/WorkbenchInspector.tsx`
- 复用：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx`
- 复用：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/auditEventStream.ts`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/test/workbenchInspector.test.tsx`

**步骤 1：编写失败的测试**

```tsx
it('shows human progress by default and keeps debug stream behind a toggle', () => {
  // 默认看人话进度，切换后才看调试流
})
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/workbenchInspector.test.tsx
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add src/test/workbenchInspector.test.tsx
git commit -m "test: add failing workbench inspector test"
```

**步骤 4：实现右栏**

要求：

- 默认显示“人话进度流”
- 调试流单独切换
- 右栏始终常驻，不再是弹窗
- 当前 Agent、当前阶段、最新动作固定显示在顶部

**步骤 5：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/workbenchInspector.test.tsx
```

预期：PASS

**步骤 6：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add src/pages/AuditWorkbench/components/WorkbenchInspector.tsx src/test/workbenchInspector.test.tsx
git commit -m "feat: add persistent workbench inspector"
```

---

### 任务 7：把目录、图纸、报告模块深度接进工作台

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench/components/views/CatalogView.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench/components/views/DrawingsView.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/AuditWorkbench/components/views/ReportView.tsx`
- 参考：现有 `ProjectDetail` 下相关组件
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/test/workbenchFlowShell.test.tsx`

**步骤 1：编写失败的测试**

```tsx
it('lets user move from catalog to drawings to report within the workbench shell', () => {
  // 至少能在同一工作台里完成这三段切换
})
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/workbenchFlowShell.test.tsx
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add src/test/workbenchFlowShell.test.tsx
git commit -m "test: add failing workbench flow shell test"
```

**步骤 4：实现一体化主流程**

要求：

- 不跳回旧详情页
- 在工作台内直接完成：
  - 目录确认
  - 图纸管理
  - 报告查看
- 报告页保留误报反馈入口

**步骤 5：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/workbenchFlowShell.test.tsx
```

预期：PASS

**步骤 6：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add src/pages/AuditWorkbench/components/views src/test/workbenchFlowShell.test.tsx
git commit -m "feat: integrate catalog drawings and report into workbench"
```

---

### 任务 8：给现有页面加入口，让两套体验共存

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectList.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail.tsx`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/test/workbenchEntry.test.tsx`

**步骤 1：编写失败的测试**

```tsx
it('shows entry points to the new workbench from project list and project detail', () => {
  // 应能跳到 /projects/:id/workbench
})
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/workbenchEntry.test.tsx
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add src/test/workbenchEntry.test.tsx
git commit -m "test: add failing workbench entry test"
```

**步骤 4：实现入口**

要求：

- 项目列表支持“打开工作台”
- 项目详情支持“切到工作台”
- 旧页面不删

**步骤 5：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/workbenchEntry.test.tsx
```

预期：PASS

**步骤 6：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add src/pages/ProjectList.tsx src/pages/ProjectDetail.tsx src/test/workbenchEntry.test.tsx
git commit -m "feat: add entry points to audit workbench"
```

---

### 任务 9：补桌面增强能力，但只做第一阶段必要项

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/electron/main.cjs`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/electron/preload.cjs`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/types/desktop.ts`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/test/desktopBridge.test.ts`

**步骤 1：编写失败的测试**

```ts
it('exposes desktop shell bridge for shell-specific features', () => {
  // 预加载层至少提供 isDesktop / openExternal / revealPath 这类入口
})
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/desktopBridge.test.ts
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add src/test/desktopBridge.test.ts
git commit -m "test: add failing desktop bridge test"
```

**步骤 4：实现桌面桥接**

第一阶段只做这些：

- `isDesktop`
- `openExternal`
- `revealPath`
- `showItemInFolder`

先不做复杂本地后端控制。

**步骤 5：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/test/desktopBridge.test.ts
```

预期：PASS

**步骤 6：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add electron src/types/desktop.ts src/test/desktopBridge.test.ts
git commit -m "feat: add minimal desktop bridge"
```

---

### 任务 10：跑一轮桌面与前端整体验证

**文件：**
- 产物：无需新增源码文件
- 验证目标：整套前端与 Electron 壳

**步骤 1：跑前端测试**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test
```

预期：PASS

**步骤 2：跑 lint**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm run lint
```

预期：PASS

**步骤 3：跑前端构建**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm run build
```

预期：PASS

**步骤 4：跑 Electron 构建**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm run electron:build
```

预期：PASS

**步骤 5：人工验收**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm run electron:dev
```

人工验收要点：

- 能打开桌面窗口
- 左栏能看审图会话
- 中栏能在五个视图间切换
- 右栏能常驻显示过程流
- 从项目列表和项目详情都能进工作台
- 旧页面还能继续用

**步骤 6：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
git add .
git commit -m "feat: add electron audit workbench"
```

---

## 最终验收标准

全部完成后，必须同时满足：

1. 现有 Web 页面仍可继续使用。  
2. 新增 `/projects/:id/workbench` 路由可进入新工作台。  
3. Electron 桌面版可正常启动。  
4. 左栏主列表是审图会话，不是普通项目菜单。  
5. 中栏能覆盖总览、目录、图纸、审图、报告五个视图。  
6. 右栏过程流常驻，不再依赖等待弹窗。  
7. 目录上传、图纸管理、审图、报告都能在工作台内串起来。  
8. 用户可以从旧页面跳到工作台，双轨共存。  


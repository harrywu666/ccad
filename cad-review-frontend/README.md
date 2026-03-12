# CAD Review Frontend

## 本地开发
- 启动开发环境：

```bash
npm install
npm run dev
```

- 常用命令：
  - `npm run build`
  - `npm run test`
  - `npm run lint`

## 运行态展示约定
- 截至 2026-03-12，前端默认面向 `chief_review` 主路径，不再围绕 legacy 阶段式流水线组织文案。
- 审图进度弹窗现在固定展示 4 段：
  - 主审派单
  - 副审执行
  - 终审复核
  - 汇总整理

- `assignment_final_review` 验收路径下，前端需要满足：
  - 1 张 assignment 只显示 1 张可见副审卡
  - 底层 skill / runner 事件只能作为卡内动作流，不能重新膨胀成新卡
  - `final_review` 和 `organizer` 必须有独立状态区，不再混在“主审汇总”里

## 验收相关测试
- 运行态视图相关测试：

```bash
./node_modules/.bin/vitest run \
  src/pages/ProjectDetail/components/__tests__/useAuditProgressViewModel.test.ts \
  src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx \
  src/pages/ProjectDetail/components/__tests__/ProjectDetail.auditState.test.ts \
  --environment jsdom
```

- 如果后端已经切到 `assignment_final_review`，前端验收时重点看：
  - 副审卡数不超过 assignment 数
  - 有独立“终审复核”卡
  - 有独立“汇总整理”卡
  - 汇总区文案反映 Markdown-first 输出，而不是旧的直接 findings 合成

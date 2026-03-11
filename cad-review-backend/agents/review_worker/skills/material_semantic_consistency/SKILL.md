---
name: material-semantic-consistency
description: Use when a review worker needs to verify whether one sheet's material table and material annotations agree, especially for missing material definitions, unused table entries, or conflicting names for the same code.
---

# Material Semantic Consistency Worker Skill

## Overview

这个 skill 专门处理“单张图里的材料表和材料标注是否一致”。它先吃已有候选，再决定哪些问题能直接确认，哪些只够保留为复核结果。

## When to Use

- 已经拿到 `worker_kind=material_semantic_consistency`
- 已经明确是单图材料问题
- 需要核对材料编号是否缺定义、未使用、同编号名称不一致
- 需要小范围复核，而不是重新跑整套材料审查

不要在这些场景用：
- 需要跨图比对材料
- 需要判断索引、尺寸、节点归属
- 需要修复运行时问题或限流问题

## Input Contract

- 必须有 `source_sheet_no`
- 优先复用已有材料候选，不自己复制规则
- 证据范围只限当前源图
- AI 复核失败时允许退回规则结果，不要把整轮跑挂

## Output Contract

- 输出必须是 JSON
- 必须给出 `status / confidence / summary`
- `status` 优先用 `confirmed / rejected / needs_review`
- 元数据里至少保留 `skill_id / skill_path / evidence_pack_id`
- 如果只有规则证据，也要给清楚的结果说明

## Common Mistakes

- 不要把全项目所有图纸一起重扫
- 不要在 AI 复核失败时把整个 worker 判死
- 不要丢掉材料编号对应的定位证据

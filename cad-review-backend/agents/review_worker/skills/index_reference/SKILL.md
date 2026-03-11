---
name: index-reference
description: Use when a review worker needs to verify whether a source sheet's index callout really points to the expected target sheet, especially for missing reverse links, missing target index numbers, or suspicious orphan indexes.
---

# Index Reference Worker Skill

## Overview

这个 skill 专门处理“源图上的索引引用到底成不成立”。它只复用系统已经收集好的候选，不自己再扫一遍全项目。

## When to Use

- 已经拿到 `worker_kind=index_reference`
- 已经有 `source_sheet_no` 和 1 个或多个 `target_sheet_nos`
- 问题类型更像 `missing_target_index_no`、`missing_reverse_link`、`orphan_index_without_target`
- 需要在很小范围内复核索引真假，而不是重新做整轮审图

不要在这些场景用：
- 需要发现跨图关系，但还没有索引候选
- 需要判断材料、尺寸、节点归属
- 需要维护全项目怀疑池

## Input Contract

- 必须有 `source_sheet_no`
- `target_sheet_nos` 可以为空，但为空时一般只够做“孤立索引”复核
- 优先复用运行时已经筛好的索引候选
- 证据只看源图和目标图，不扩到无关图纸

## Output Contract

- 输出必须是 JSON
- 必须给出 `status / confidence / summary`
- `status` 只能是 `confirmed / rejected / needs_review`
- 元数据里至少保留 `skill_id / skill_path / evidence_pack_id`
- 证据不足时允许返回 `needs_review`，不要硬判

## Common Mistakes

- 不要自己重做一套候选收集规则
- 不要把目标图范围放大成全项目扫描
- 不要把“没看到证据”直接当成“引用不成立”

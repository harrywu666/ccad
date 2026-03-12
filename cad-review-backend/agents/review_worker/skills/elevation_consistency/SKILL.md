---
name: elevation-consistency
description: Use when a review worker needs to compare elevation values across paired sheets, especially for inconsistent level numbers, missing matching marks, or unclear height references that should be escalated instead of guessed.
---

# Elevation Consistency Worker Skill

## Overview

这个 skill 专门处理“跨图标高值是不是一致”。它只在已经确定图纸配对后工作，重点看同一位置、同一构件或同一参照系里的标高是否冲突。

## When to Use

- 已经拿到 `worker_kind=elevation_consistency`
- 已经明确是成对图纸之间的标高比对
- 需要确认标高值冲突、缺失对应标高或标高表达不清
- 需要基于已收集的尺寸候选做局部复核

不要在这些场景用：
- 需要做单图尺寸抽取
- 需要判断材料、索引、节点归属
- 需要在没有目标图的前提下硬做标高比对

## Input Contract

- 必须有 `source_sheet_no`
- 通常也要有至少 1 个 `target_sheet_nos`
- 优先复用已有尺寸候选，不自己复制采集逻辑
- 证据包要保留源图、目标图和冲突位置

## Output Contract

- 输出必须是 JSON
- 必须给出 `status / confidence / summary`
- `status` 优先用 `confirmed / rejected / needs_review`
- 元数据里至少保留 `skill_id / skill_path / evidence_pack_id`
- 遇到标高证据不完整时，优先返回 `needs_review`，不要瞎猜

## Common Mistakes

- 不要把普通尺寸冲突和标高冲突混在一起
- 不要在目标图缺失时伪造结论
- 不要只给结论，不给冲突位置和图纸对

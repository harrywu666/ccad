---
name: spatial-consistency
description: Use when a review worker needs to compare paired sheets for spatial or dimensional consistency, especially for conflicting geometry dimensions, mismatched room spans, or inconsistent layout distances that need localized evidence review.
---

# Spatial Consistency Worker Skill

## Overview

这个 skill 专门处理“跨图空间关系和尺寸关系是不是一致”。它会复用已经筛好的成对问题，只在源图和目标图之间做局部复核。

## When to Use

- 已经拿到 `worker_kind=spatial_consistency`
- 已经明确是跨图空间或尺寸一致性问题
- 需要核对同一位置在不同图纸里的尺寸、开间、进深、距离是否冲突
- 需要把局部冲突整理成能交给主审收敛的结果卡

不要在这些场景用：
- 需要做全项目尺寸扫图
- 需要判断标高专项、材料专项、索引专项
- 需要修运行时调度、限流或重试逻辑

## Input Contract

- 必须有 `source_sheet_no`
- 一般至少要有 1 个 `target_sheet_nos`
- 只复用成对尺寸候选，不复制旧的总入口实现
- 证据包要保留图纸对、位置、规则编号和严重程度

## Output Contract

- 输出必须是 JSON
- 必须给出 `status / confidence / summary`
- `status` 优先用 `confirmed / rejected / needs_review`
- 元数据里至少保留 `skill_id / skill_path / evidence_pack_id`
- 如果只拿到规则证据，也要明确写出问题数量和定位

## Common Mistakes

- 不要把全项目所有尺寸一次性塞进这个 worker
- 不要把空间一致性和节点归属混成一个结论
- 不要丢掉问题数量、规则编号和证据包编号

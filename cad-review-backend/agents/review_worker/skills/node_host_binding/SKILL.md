---
name: node-host-binding
description: Use when a review worker needs to verify whether a detail node, section marker, or callout on the source sheet really belongs to the expected parent sheet, especially for missing mother-sheet links, missing reverse references, or suspicious detached detail symbols.
---

# Node Host Binding Worker Skill

## Overview

这个 skill 专门处理“节点到底挂在哪张母图上”。它只在主审已经圈出源图和目标图后做小范围复核，不重新扫描全项目关系。

## When to Use

- 已经拿到 `worker_kind=node_host_binding`
- 已经明确有 `source_sheet_no` 和 1 个或多个 `target_sheet_nos`
- 问题更像“节点母图缺失”“节点挂错图”“详图和母图对不上”
- 需要在一小组相关图之间确认节点归属真假

不要在这些场景用：
- 需要从零发现跨图关系
- 需要判断索引、材料、尺寸问题
- 需要重建全项目关系图

## Input Contract

- 必须有 `source_sheet_no`
- `target_sheet_nos` 不能为空；为空时一般不够判断节点归属
- 证据范围只限源图和目标图，不扩到无关图纸
- 优先复用运行时已经准备好的关系发现能力，不复制一套新规则

## Output Contract

- 输出必须是 JSON
- 必须给出 `status / confidence / summary`
- `status` 只能是 `confirmed / rejected / needs_review`
- 元数据里至少保留 `skill_id / skill_path / evidence_pack_id`
- 如果源图或目标图缺失，允许直接返回 `rejected`，但要把原因写清楚

## Common Mistakes

- 不要把“暂时没找到目标图”说成“节点一定挂错”
- 不要把证据范围放大成全项目重扫
- 不要丢掉节点所在源图、目标图和定位描述

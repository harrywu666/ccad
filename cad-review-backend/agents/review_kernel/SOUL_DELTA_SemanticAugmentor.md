# SOUL_DELTA.md — SemanticAugmentor 特有约束

继承：SOUL.md 全部条款
本文件只补充 SemanticAugmentor 特有的克制边界

---

## 特有 Never Events

- Never 在 CandidateBindings 之外自由发明绑定目标——我只在候选集内工作
- Never 把空间名称相似（如"主卧"和"次卧"同含"卧"）作为对齐的充分依据
- Never 在 geometry_overlap_ratio < 0.30 时输出空间对齐结论，除非有极强名称证据
- Never 修改上游 confidence ≥ 0.80 的对象分类——那是已确定的结论

## 特有 Truth Model 补充

- 索引归一必须以 DrawingRegister 中存在的 sheet_number 为约束
- 空间对齐以几何重叠为主权重，名称语义为辅权重，两者均弱时必须 unresolved

## 特有 Uncertainty Discipline

- 节点编号解析出多个可能（如"A601-3"既可能是 sheet A-601 node 3，也可能是 sheet A601 node 3），必须两种都列出，交由下游或人工确认

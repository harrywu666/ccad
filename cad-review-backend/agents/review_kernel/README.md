# review_kernel 提示词资产说明

本目录是新审图内核（`services/review_kernel`）唯一使用的 AGENT/SOUL 资产源。

文件映射关系：

- `SOUL.md`：全局信条（所有阶段共享）
- `AGENT_PageClassifier.md` + `SOUL_DELTA_PageClassifier.md`：弱辅助阶段
- `AGENT_SemanticAugmentor.md` + `SOUL_DELTA_SemanticAugmentor.md`：候选消歧阶段
- `AGENT_ReviewReporter.md` + `SOUL_DELTA_ReviewReporter.md`：报告表达阶段
- `AGENT_ReviewQA.md` + `SOUL_DELTA_ReviewQA.md`：问答阶段（预留）

代码入口：

- `services/review_kernel/prompt_assets.py`


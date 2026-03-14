# 审图 JSON 全量补齐 实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 一次性补齐 DWG→JSON（含 IR）对 5 份规范的关键缺口，使输出结构满足“可审图、可追溯、可降级、可LLM安全消费”。

**架构：** 保持现有 review_kernel 主链路不变，在“提取层 + IR 编译层”增补扩展字段和降级日志；规则引擎保持兼容，优先新增结构化数据，不破坏既有行为。

**技术栈：** Python、ezdxf、pytest、现有 review_kernel/dxf pipeline。

---

### 任务 1：提取层补齐扩展数据

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/dxf/viewport.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/dxf/entity_extraction.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/dxf/pipeline.py`

**步骤：**
1. 为 viewport 增加 clip boundary 结构（至少支持 rectangular / none，附 source 与降级标记）。
2. 为 INSERT 增加动态块元数据（is_dynamic_block、dynamic_params、effective_geometry、degraded_reason）。
3. 为文本增加编码与 OCR fallback 元数据（encoding_detected、encoding_confidence、ocr_triggered、ocr_fallback）。
4. 为可提取对象增加 z_min/z_max/z_range_label/elevation_band。
5. 输出 layer_state_snapshot 和 viewport layer_overrides 统一结构。

### 任务 2：IR 编译层补齐规范对象

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/review_kernel/ir_compiler.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/review_kernel/orchestrator.py`

**步骤：**
1. 在 IR 顶层新增 project / drawing_register 聚合对象（兼容单图与全项目模式）。
2. 补齐 block_semantic_profiles、layer_state_snapshots、sanitization_logs、encoding_evidence、z_range_summary。
3. 增加 clear_height_chains、elevation_views/elevation_zones/elevation_elements 的可降级对象。
4. 为空间对象增加 cross_document_refs 与 alignment_basis。
5. 保持 schema_version=1.2.0，新增字段全部向后兼容。

### 任务 3：LLM 消费与边界兼容核对

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/review_kernel/context_slicer.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/review_kernel/llm_boundary.py`

**步骤：**
1. 在切片中增加新证据字段，但继续禁止 raw 层直喂。
2. 维持 token 预算裁剪优先级，新增字段参与预算。
3. 保持 high severity 与置信度传播门禁不变。

### 任务 4：测试补齐

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_review_kernel_ir_compiler.py`
- 新增：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_review_kernel_extensions.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_review_kernel_pipeline.py`

**步骤：**
1. 为新增扩展字段增加断言（存在性、降级标记、可追溯链）。
2. 为动态块/裁剪/编码回退/Z 过滤增加最小样例测试。
3. 确认旧规则引擎测试不回归。

### 任务 5：验证与交付

**文件：**
- 无代码新增，执行验证命令

**步骤：**
1. 运行 review_kernel 相关测试集合。
2. 运行 cutover/status 关键测试集合。
3. 汇总通过数、warning来源、剩余风险（若有）。

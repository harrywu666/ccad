# 文档一：产品需求文档（PRD V4.0）
## 室内装饰施工图 AI 自动审核系统

**版本：V4.0 | 日期：2026年3月 | 状态：基于代码实现更新**

---

## 一、产品概述

### 1.1 产品是什么

一款专为室内装饰行业设计的施工图自动审核软件。设计师或审图员上传一套完整的施工图文件，系统自动完成图纸的整理、匹配、审核，最终输出一份详细的审核报告。

整个审核过程模拟真人审图员的工作方式：先看目录了解图纸全貌，再逐张读图理解内容，最后跨图比对找出问题。

### 1.2 解决什么问题

室内装饰施工图审核是一项高度重复、耗时且容易出错的工作。一套完整的施工图通常有几十到上百张图纸，审图员需要在平面图、立面图、大样图之间反复翻阅比对，常见的问题包括：

- 平面图和立面图的同一面墙尺寸标注不一致
- 图纸中的材料标注与材料表对不上
- 索引符号指向的图纸不存在或内容对不上
- 图纸目录与实际图纸数量不符

这些错误如果流入施工阶段，轻则返工，重则造成重大损失。本软件通过AI+精确数据的方式，自动完成这些重复性的比对工作。

### 1.3 目标用户

- 室内设计师（自查用）
- 设计公司审图部门
- 施工图审查机构
- 甲方工程管理部门

### 1.4 核心竞争力

开发者具有多年室内设计从业经验，深度理解图纸审核的业务逻辑。同时系统采用「三线数据融合」技术路线，确保审核结果的高准确性和可追溯性。

---

## 二、技术架构

### 2.1 核心设计思想

系统采用「三线数据并行 + 汇合匹配」的架构设计：

```
数据线1：目录PNG  →  AI视觉识别  →  图纸目录（锚点）
数据线2：PDF     →  逐页转PNG  →  AI视觉识别分析图名图号  →  匹配目录
数据线3：DWG     →  ODA转DXF  →  ezdxf提取JSON   →  绑定图纸
                                     ↓
                             三线汇合匹配
                                     ↓
                         图纸上下文构建(L0/L1/L2)
                                     ↓
                         审核任务规划与执行
                                     ↓
                             AI交叉核对
                                     ↓
                         生成完整审核报告
```

### 2.2 数据层说明

**目录数据（Catalog）：**
- 用户上传目录页PNG，AI视觉识别提取图号、图名、版本、日期
- 作为整套图纸的「权威锚点」，所有图纸向目录对齐
- 支持用户校对后锁定（status=locked），锁定后不可随意修改

**图纸PNG数据（Drawing）：**
- PDF图纸流式逐页转PNG（300DPI），AI通过图像理解图纸内容
- AI视觉识别每张图纸的图号和图名，自动与目录匹配
- 支持版本管理（data_version），重新上传时保留历史版本

**DWG精确数据（JsonData）：**
- DWG通过ODA File Converter转为DXF，使用ezdxf按Layout提取
- 精确提取：索引符号、尺寸标注、材料标注、材料表、图层状态、视口信息
- 所有坐标数据经换算为百分比（global_pct），实现跨图定位

### 2.3 技术栈

**后端：**
- FastAPI + SQLAlchemy + SQLite
- AI大模型 API用于图像识别和自然语言处理
- ODA File Converter + ezdxf 用于DWG数据处理
- PyMuPDF 用于PDF转PNG

**前端：**
- React + TypeScript + Tailwind CSS
- shadcn/ui 组件库
- 响应式设计支持

---

## 三、数据模型

### 3.1 核心实体

**Project（项目）**
- id, name, category, tags, description
- status: new → catalog_locked → matching → ready → auditing → done
- cache_version 用于前端缓存同步

**Catalog（图纸目录）**
- project_id, sheet_no, sheet_name, version, date
- status: pending / locked
- sort_order 维护目录顺序

**Drawing（图纸PNG）**
- project_id, catalog_id, sheet_no, sheet_name
- png_path, page_index, data_version
- status: unmatched / matched
- replaced_at 标记历史版本

**JsonData（DWG提取数据）**
- project_id, catalog_id, sheet_no
- json_path, data_version, is_latest
- summary 存储数据摘要（视口数、标注数等）

**AuditResult（审核结果）**
- project_id, audit_version, type(index/dimension/material)
- severity(error/warning), sheet_no_a, sheet_no_b
- location, value_a, value_b, description
- evidence_json 存储定位证据（锚点信息）
- is_resolved, feedback_status 用于人工处理追踪

**AuditRun（审核运行记录）**
- project_id, audit_version, status(running/done/failed)
- current_step, progress, total_issues
- 用于异步任务进度追踪

**AuditTask（审核任务规划）**
- task_type(index/dimension/material)
- source_sheet_no, target_sheet_no, priority, status
- 用于细粒度的审核任务管理

**SheetContext（图纸上下文分层）**
- layer_l0（图纸元数据）、layer_l1（内容摘要）、layer_l2（详细数据）
- 用于审核前的图纸关系构建

### 3.2 版本管理机制

- 图纸PNG支持多版本（data_version），重新上传时不删除旧数据
- JSON数据通过is_latest标记最新版本，历史版本保留
- 审核结果按audit_version隔离，支持多版本审核历史

---

## 四、用户使用流程

### 4.1 完整操作步骤

```
第一步：新建项目
用户输入项目名称、选择分类、添加标签和描述
→ 系统创建项目并初始化目录结构

第二步：上传目录
上传图纸目录页的PNG或PDF
→ AI视觉识别提取目录条目（图号、图名、版本、日期）
→ 前端展示识别结果，用户校对修改
→ 确认锁定目录（目录状态变为locked，成为后续匹配锚点）

第三步：上传PDF图纸
上传完整的施工图PDF（一个PDF包含所有图纸）
→ 系统流式逐页转PNG（300DPI）
→ 每张PNG立即提交AI视觉识别分析图名图号
→ 自动与锁定目录匹配（支持模糊匹配算法）
→ 前端实时展示匹配进度和结果
→ 未能自动匹配的图纸，用户可手动指定

第四步：上传DWG文件
上传对应的DWG文件（支持批量）
→ ODA File Converter批量转为DXF
→ ezdxf按Layout提取JSON数据
→ 自动匹配目录（支持布局名、图签中的图号匹配）
→ 目录未匹配的图纸生成占位JSON
→ 前端展示提取结果和匹配状态

第五步：确认三线匹配
前端展示完整的匹配关系表：
目录条目 ←→ 图纸PNG ←→ JSON数据
→ 显示就绪/缺失状态统计
→ 用户确认无误后，点击「开始审核」

第六步：等待审核完成
系统自动执行：
1. 构建图纸上下文（提取L0/L1/L2层信息）
2. 规划审核任务图（基于索引关系生成任务列表）
3. 索引核对（检测断链、反向缺失、孤立索引）
4. 尺寸核对（5图输入AI对比：全图+4象限高清图）
5. 材料核对（材料表与图纸标注交叉验证）
→ 前端实时展示审核进度（步骤+百分比）

第七步：查看审核报告
前端展示完整审核结果：
- 概览区：问题总数、分类统计、整体评级
- 索引问题列表（支持分组展示）
- 尺寸问题列表（含AI自然语言描述和定位信息）
- 材料问题列表
→ 支持问题定位预览（高亮显示在图纸上的位置）
→ 可下载PDF/Excel报告

第八步：人工复核与反馈
→ 标记问题为已解决
→ 提交误报反馈（incorrect），系统记录到feedback_samples
→ 用于后续模型优化
```

### 4.2 项目状态流转

```
new（新建）
  ↓ 上传目录并锁定
catalog_locked（目录已锁定）
  ↓ 上传PDF/DWG
matching（匹配中）
  ↓ 三线全部就绪
ready（就绪）
  ↓ 开始审核
auditing（审核中）
  ↓ 审核完成
done（审核完成）
```

---

## 五、核心审核功能

### 5.1 第一步：索引核对

**核对逻辑：**
- 提取所有图纸中的索引符号（INSERT实体，含REF#、SHT等属性）
- 建立索引发出方和接收方的对应关系
- 检测四类问题：
  1. 断链-目标图不存在（有发出但目录/数据中无目标图）
  2. 断链-编号缺失（目标图存在但无对应编号索引）
  3. 反向缺失（A→B存在但B→A不存在）
  4. 孤立索引（有编号无目标且未被引用）

**输出：**
- 完整索引对照表
- 每个问题包含：源图纸、目标图纸、索引编号、问题描述、定位锚点

### 5.2 第二步：尺寸核对

**技术路线（文档六实现）：**
采用「5图输入」策略解决A1大图AI看不清细节的问题：
- 图1：全图（150DPI，叠加24×17网格坐标）
- 图2-5：四个象限高清图（300DPI，20%重叠避免边界截断）

**核对流程：**
1. 单图语义分析：AI解析每张图的尺寸语义（id、semantic、location_desc、dim_type、value、grid、component）
2. 双图对比：基于索引关系，对比相关图纸的同一构件尺寸
3. 差异判定：
   - 差值=0：一致
   - 0<差值≤3mm：工程精度内，忽略
   - 3mm<差值≤10mm：可能精度差异，confidence 0.3-0.5
   - 差值>10mm：不一致，confidence 0.7+

**输出：**
- 涉及图纸（图号+图名）
- 具体位置描述（如：B-C轴/①-②轴范围内的东侧墙体）
- 平面图数值 vs 立面图数值
- 差值
- AI生成的自然语言描述
- 定位锚点（grid坐标、global_pct百分比位置）

### 5.3 第三步：材料核对

**核对内容：**
- 材料表中的编号和名称 vs 图纸引线标注
- 未定义材料（图纸中有但材料表无）
- 未使用材料（材料表有但图纸中无）
- 同编号不同名称（AI做语义匹配检测别名冲突）

**输出：**
- 问题类型（未定义/未使用/名称不一致）
- 涉及图纸和位置
- 材料编号和名称
- AI自然语言描述

---

## 六、高级功能

### 6.1 问题定位与预览

**证据系统（Evidence）：**
- 每个审核结果包含evidence_json，存储定位锚点
- 锚点信息：role(source/target)、sheet_no、grid、global_pct(x,y)、confidence
- 支持从审核结果直接定位到图纸具体位置

**图纸标注：**
- DrawingAnnotation表支持按audit_version隔离的图纸标注
- 用户可在图纸上做手写标注（stroke）、文字标注（text）
- 用于人工复核时标记问题位置

### 6.2 审核任务规划

**TaskPlannerService：**
- 基于图纸上下文和索引关系生成审核任务图
- 任务类型：index（单图核对）、dimension（双图对比）、material（双图材料）
- 优先级算法：平面图（A1开头/含"平面"）优先级更高（1-2级），其他图3-4级
- 避免重复：同一task_type+source+target只生成一个任务

**异步执行：**
- 使用线程池并发执行任务
- 支持取消操作（通过cancel_registry）
- 实时更新AuditRun的progress和current_step

### 6.3 缓存与性能优化

**多级缓存：**
- 尺寸核对缓存：按项目存储sheet语义和pair对比结果（SHA256键）
- Layout缓存：缓存DWG的layout_page_range和indexes（LRU，基于文件mtime）
- 前端缓存：cache_version机制，服务端变化时自动刷新

**并发控制：**
- 图纸识别并发：AI_PAGE_CONCURRENCY（默认20）
- 尺寸核对并发：SHEET_AGENT_CONCURRENCY（默认8）+ PAIR_AGENT_CONCURRENCY（默认16）
- 使用asyncio.Semaphore控制

### 6.4 审查技能包（Skill Pack）

**AuditSkillEntry表：**
- 支持全局可配置的审查规则
- 字段：skill_type, title, content, execution_mode(ai/rule)
- 支持关联stage_keys，在特定审核阶段注入规则
- 支持优先级排序

**提示词覆盖：**
- AIPromptSetting表支持按stage_key覆盖系统默认提示词
- 支持变量占位符（{{payload_json}}等）
- 内置8个提示词阶段：目录识别、图纸识别、图纸汇总、目录匹配、任务规划、尺寸单图分析、尺寸双图对比、材料审核

### 6.5 误报反馈与样本管理

**FeedbackSample表：**
- 独立于AuditResult的训练数据存储层
- 记录用户标记的误报样本（feedback_status=incorrect）
- 包含问题完整信息、用户备注、快照数据
- curation_status支持样本策展流程（new → curated）

---

## 七、审核报告

### 7.1 前端展示

**概览区：**
- 审核项目名称和日期
- 总问题数 + 各类型数量（索引/尺寸/材料）
- 整体评级（通过/需整改/严重问题）
- 审核版本切换（支持查看历史审核结果）

**问题列表：**
- 索引问题：按图号分组展示，支持展开查看所有位置
- 尺寸问题：显示完整自然语言描述 + 数值差异 + 定位信息
- 材料问题：显示材料冲突详情
- 每条问题可标记「已解决」或「误报」

**问题定位：**
- 点击问题可打开图纸预览
- 支持缩略图导航、缩放、平移
- 高亮显示问题位置（基于evidence_json中的锚点）

### 7.2 可下载报告

**PDF报告：**
- 封面（项目名称、审核日期、问题总数）
- 问题概览表
- 各类问题详细列表（含AI自然语言描述和定位信息）
- 问题定位图（在图纸PNG上标出问题位置）

**Excel报告：**
- Sheet1：概览统计
- Sheet2：索引问题清单
- Sheet3：尺寸问题清单
- Sheet4：材料问题清单
- 每列包含：图号、图名、位置、问题描述、严重程度、数值A、数值B

---

## 八、产品边界（不做什么）

- 不做CAD图纸的在线编辑功能
- 不做云端DWG存储（DWG文件本地处理，不上传服务器）
- 不做设计规范检查（通道净宽、房间面积等）
- 不做自动修改图纸功能
- 不做多人实时协作（当前为单用户模式）

---

## 九、部署与配置

### 9.1 环境变量

**AI视觉识别 API：**
- AI_API_KEY：AI API密钥

**ODA File Converter：**
- ODA_FILE_CONVERTER_PATH：可选，自定义ODA路径
- 默认路径：
  - macOS: /Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter
  - Windows: C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe

**并发配置：**
- AI_PAGE_CONCURRENCY：图纸识别并发数（默认20）
- SHEET_AGENT_CONCURRENCY：尺寸单图分析并发数（默认8）
- PAIR_AGENT_CONCURRENCY：尺寸双图对比并发数（默认16）

**数据存储：**
- CCAD_DB_PATH：SQLite数据库路径（可选，默认~/cad-review/db/database.sqlite）
- 项目文件存储：~/cad-review/projects/{project_name}_{project_id}/

### 9.2 依赖要求

**后端：**
- Python 3.10+
- FastAPI, SQLAlchemy, pydantic
- ezdxf, PyMuPDF, Pillow
- httpx（AI视觉识别 API调用）

**外部工具：**
- ODA File Converter（必须，用于DWG转DXF）

---

## 十、后期迭代方向

### 10.1 短期（1-3个月）

- [ ] 审核结果导出Word格式
- [ ] 批量项目操作（批量删除、批量导出）
- [ ] 审核报告对比（版本间差异分析）
- [ ] 问题严重性自定义配置

### 10.2 中期（3-6个月）

- [ ] 支持中望CAD格式
- [ ] 规范库（国标室内装饰规范自动检查）
- [ ] 历史审核记录趋势分析
- [ ] 误报反馈驱动的提示词自动优化

### 10.3 长期（6-12个月）

- [ ] 与项目管理平台集成（如蓝湖、MasterGo）
- [ ] 团队协作功能（多用户、权限管理）
- [ ] 机器学习模型微调（基于积累的feedback_samples）
- [ ] 移动端审核报告查看App

---

## 十一、API概览

### 11.1 项目管理
- GET /api/projects - 获取项目列表
- POST /api/projects - 创建项目
- GET /api/projects/{id} - 获取项目详情
- PUT /api/projects/{id} - 更新项目
- DELETE /api/projects/{id} - 删除项目

### 11.2 目录管理
- GET /api/projects/{id}/catalog - 获取目录
- POST /api/projects/{id}/catalog/upload - 上传目录图片
- PUT /api/projects/{id}/catalog - 更新目录
- POST /api/projects/{id}/catalog/lock - 锁定目录

### 11.3 图纸管理
- GET /api/projects/{id}/drawings - 获取图纸列表
- POST /api/projects/{id}/drawings/upload - 上传PDF
- GET /api/projects/{id}/drawings/upload-progress - 获取上传进度
- PUT /api/projects/{id}/drawings/{drawing_id} - 更新图纸匹配

### 11.4 DWG管理
- GET /api/projects/{id}/dwg - 获取JSON数据列表
- POST /api/projects/{id}/dwg/upload - 上传DWG
- GET /api/projects/{id}/dwg/upload-progress - 获取上传进度

### 11.5 审核管理
- GET /api/projects/{id}/audit/status - 获取审核状态
- GET /api/projects/{id}/audit/three-lines - 获取三线匹配状态
- POST /api/projects/{id}/audit/start - 开始审核
- POST /api/projects/{id}/audit/stop - 停止审核
- GET /api/projects/{id}/audit/results - 获取审核结果
- PATCH /api/projects/{id}/audit/results/{result_id} - 更新结果状态

### 11.6 系统设置
- GET /api/settings/prompt-stages - 获取提示词阶段配置
- PUT /api/settings/prompt-stages - 更新提示词
- GET /api/skill-pack/rules - 获取技能包规则
- POST /api/skill-pack/rules - 添加规则

---

## 十二、附录：数据字典

### 12.1 审核结果类型
- index：索引问题
- dimension：尺寸问题
- material：材料问题

### 12.2 严重程度
- error：错误（如索引断链）
- warning：警告（如尺寸不一致）
- info：信息（如孤立索引）

### 12.3 问题状态
- none：未处理
- incorrect：误报（已反馈）
- resolved：已解决

### 12.4 项目状态
- new：新建
- catalog_locked：目录已锁定
- matching：匹配中
- ready：就绪
- auditing：审核中
- done：审核完成

---

*PRD版本：V4.0 | 基于代码实现更新 | 2026年3月*

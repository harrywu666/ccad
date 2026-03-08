# 图框优先的多图布局切分设计

**日期：** 2026-03-08

## 背景

当前 DWG 提取链路默认采用：

- 一个 `layout` 对应一张图纸
- 从 `layout_name / title_blocks / sheet_no` 中抽取唯一图号
- 生成一个 `layout JSON`

这套假设对 `test1`、`test4` 这类“一布局一图”的项目成立，但对 `test2`、`test3` 这类“一个布局里包含多张图纸 / 多个视口 / 多个详图单元”的项目不成立。

离线自测已经确认：

- `test1`：提取正常，`sheet_no_empty = 0`
- `test4`：提取正常，`sheet_no_empty = 0`
- `test2`：能提取 JSON，但 `7` 个 layout JSON 里有 `6` 个 `sheet_no` 为空
- `test3`：能提取 JSON，但 `4` 个 layout JSON 全部 `sheet_no` 为空

这说明问题不是“DWG 完全不能转 JSON”，而是：

- 当前提取器把多图 layout 错当成单图 layout
- 标题块、图号、尺寸、材料、索引等对象没有先归属到某一个图纸单元
- 后续目录匹配和审图任务构建因此失真或退化成 placeholder

## 用户目标

系统需要适配这种常见生产形态：

- 一个 layout 内存在多张图纸
- 一个 layout 内存在多个视口、多组标题块、多组详图号
- 系统仍能正确识别每张子图的图框、图号、图名、比例和语义对象

并且必须把**图框识别**作为基础能力，因为它同时决定：

- 图幅判断
- 图纸范围
- 坐标归一化基线
- 一个 layout 内到底有几张独立图纸单元

## 非目标

- 不把所有项目都强制改成“按 viewport 切图”
- 不在这一轮直接改 AI 审核策略
- 不在这一轮改 PDF 展示层
- 不为了 `test2/test3` 单独硬编码某一套项目规则

## 设计原则

1. **图框优先**
   - 图框识别先于 viewport 识别
   - 图框是图幅、范围和坐标系统的唯一基石
2. **向后兼容**
   - 单图 layout 继续走现有主链路
   - 只有检测到多图 layout 时才进入新分裂逻辑
3. **语义先归属，再审核**
   - 索引、尺寸、材料、标题块必须先归属到某一个图框单元，再进入目录匹配和审图
4. **可解释**
   - 每个 fragment 必须能说明它来自哪个 layout、哪个图框、哪个标题块
5. **渐进落地**
   - 先支持检测和切分
   - 再接入目录匹配
   - 最后扩展到上下文构建和审图任务规划

## 方案比较

### 方案一：继续坚持“一 layout 一图”

只增强 `sheet_no / title_blocks` 的识别规则。

优点：

- 改动小
- 对 `test1/test4` 风险低

缺点：

- 无法覆盖一个 layout 多张图纸的真实情况
- 标题块和语义对象依旧会混在一起
- 后续目录匹配和坐标系统仍不可靠

结论：不采用。

### 方案二：纯 viewport 切图

把一个 layout 内的每个 viewport 当作一张图纸。

优点：

- 直观
- 对部分拼版图纸有效

缺点：

- 很多图纸并不严格依赖 viewport 表达
- 标题块、详图号、尺寸、材料未必与 viewport 一一对应
- 无法解决图幅和图框边界问题

结论：不采用。

### 方案三：图框优先的 layout 内分图

先识别图框，再在每个图框内部识别标题块、图号、图名、比例、viewport 和语义对象，最终输出多个 fragment。

优点：

- 能同时覆盖单图 layout 和多图 layout
- 图幅和坐标系统更稳
- 目录匹配和审图任务构建可以建立在 fragment 级别
- 与后续 PDF/DWG 坐标统一方向一致

缺点：

- 改动范围较大，需要重构提取结果模型

结论：采用。

## 核心概念

### 1. `layout_frame`

表示一个 layout 中的独立图纸单元。建议字段：

- `frame_id`
- `layout_name`
- `frame_bbox`
- `paper_size_hint`
- `orientation`
- `title_block_bbox`
- `sheet_no`
- `sheet_name`
- `scale`
- `confidence`
- `source = frame_detection`

### 2. `layout_fragment`

表示从一个 layout 中切分出的可独立审核图纸片段。建议字段：

- `fragment_id`
- `layout_name`
- `frame_id`
- `sheet_no`
- `sheet_name`
- `scale`
- `bbox`
- `viewports`
- `indexes`
- `dimensions`
- `materials`
- `title_blocks`
- `detail_titles`
- `layers`
- `fragment_confidence`

### 3. `multi_sheet_layout`

表示一个 layout 中识别到多个有效图纸单元。建议触发条件：

- 识别到多个独立图框
- 或多个强标题块候选，且空间上明显分离
- 或多个详图标题单元与多个几何聚类相互对应

## 识别流程

### 第一步：图框识别

这是整个能力的底座。

优先识别以下对象：

- 外边框矩形或封闭 polyline
- 标题栏 / 图签区域
- 常见图框图层或块
- 纸面边界附近的大矩形轮廓

输出：

- 每个图框的 `bbox`
- 纸张方向：横向 / 纵向
- 图幅候选：A0/A1/A2/A3/非常规

### 第二步：标题块和详图标题识别

在每个图框内部优先找：

- 图号
- 图名
- 比例
- 详图标题
- `DN / TITLE1 / TITLE2 / TITLE3 / SHEETNO`

要求：

- 不再在整个 layout 上做唯一图号假设
- 所有标题类对象都先落到某个图框内

### 第三步：viewport 与几何内容归属

在图框内部识别：

- viewport
- 尺寸
- 材料
- 索引
- 详图标题块
- 图签相关对象

归属规则优先级：

1. 明确位于图框内
2. 与图框内标题块距离最近
3. 与图框内 viewport 范围重叠最多

### 第四步：生成 fragment 级 JSON

不再只写一个 `layout JSON`，而是：

- 单图 layout：仍写一个 fragment，可视为当前兼容模式
- 多图 layout：为每个图框单元写一个 fragment JSON

建议命名方式：

- `dwgname__layout__fragment-sheet-no.json`

同时保留父级 layout 信息，便于回溯。

## 坐标系统设计

### 当前问题

当前很多坐标基于：

- 整个 layout
- 或整张 PDF 页面

这在多图 layout 中会混淆多个独立图纸单元。

### 调整后

所有审核相关坐标应优先落在 `frame_bbox` 坐标系中：

- `frame_local_pct`
- `frame_grid`
- 再映射回 layout/page 坐标

这样可以：

- 稳定处理不同图幅
- 在多图 layout 中避免跨图误归属
- 为后续 PDF/DWG registration 提供稳定基线

## 目录匹配策略

### 当前模式

- 一个 layout JSON 匹配一个目录项

### 调整后

- 一个 `layout_fragment` 匹配一个目录项
- 同一 DWG 文件可对应多个目录项

匹配依据：

- `sheet_no`
- `sheet_name`
- 标题块文本
- 详图标题
- 图框内标题栏信息

对多图 layout，必须先按 fragment 匹配目录，再进入上下文构建。

## 对现有链路的影响

### 1. DWG 上传阶段

- 需要从 layout-level 提取升级为 fragment-level 提取
- `JsonData` 仍可沿用，但内容应标记 fragment 来源

### 2. 三线匹配

- 目录与 DWG 的匹配单位从 layout 改为 fragment
- placeholder 的生成逻辑不能再把“多图 layout 未切开”误判为缺数据

### 3. 图纸上下文构建

- `SheetContext` 应按 fragment 构建
- `SheetEdge` 也应基于 fragment 的索引关系生成

### 4. 审核任务图

- 索引、尺寸、材料任务全部基于 fragment 而不是整个 layout

## 风险与应对

### 风险一：图框识别误检

可能把装饰边线或局部几何误识别成图框。

应对：

- 结合标题栏区域
- 结合图幅长宽比
- 结合边界位置
- 给出 frame confidence

### 风险二：一个图框内存在多个详图单元

某些 detail sheet 自己仍然是拼版。

应对：

- 图框作为第一层
- 标题块 / 详图标题作为第二层拆分信号

### 风险三：现有正常项目被破坏

应对：

- 默认先做 `multi_sheet_layout` 检测
- 单图 layout 继续沿用现有路径

## 验证目标

### `test1`

- 保持当前正常提取效果不回退

### `test4`

- 保持当前正常提取效果不回退

### `test2`

- 目标是把当前大量 `sheet_no=""` 的 layout 进一步切成可匹配 fragment

### `test3`

- 目标是让当前空 `sheet_no` 的 layout 至少能形成可识别图框单元，并提取有效图号/图名

## 推荐实施顺序

1. 先做图框检测与 `multi_sheet_layout` 检测
2. 再产出 fragment 级 JSON
3. 再接目录匹配
4. 再接上下文构建与任务规划
5. 最后回到预览与定位层做坐标适配

## 结论

这次需要补的不是单个项目规则，而是一个新的 DWG 结构化基础能力：

- **图框优先**
- **layout 内分图**
- **fragment 级目录匹配**
- **frame 坐标系优先**

这是解决 `test2/test3` 这类“一布局多图纸”项目的正确方向，也是后续稳定坐标系统的必要前提。

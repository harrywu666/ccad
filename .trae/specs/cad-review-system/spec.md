# 室内装饰施工图AI自动审核系统 开发规格文档

## Why

室内装饰施工图审核是一项高度重复、耗时且容易出错的工作。一套完整的施工图通常有几十到上百张图纸，审图员需要在平面图、立面图、大样图之间反复翻阅比对。人工审核容易出现尺寸标注不一致、材料标注缺失、索引引用错误等问题，流入施工阶段会造成返工和损失。

本项目通过AI+精确数据的方式，自动完成这些重复性的比对工作，模拟真人审图员的工作方式：先看目录了解图纸全貌，再逐张读图理解内容，最后跨图比对找出问题。

## What Changes

本项目是一个完整的室内装饰施工图AI自动审核系统，包含：

### 核心功能模块
- **项目管理** - 项目创建、分类管理、标签、搜索、删除
- **目录识别** - 上传目录PNG，Kimi AI识别图纸目录条目，用户校对后锁定
- **图纸匹配** - PDF上传转PNG，流式处理逐页识别图名图号，自动匹配目录
- **DWG数据提取** - CAD插件提取JSON精确数据（尺寸、索引、材料），版本管理
- **三线匹配** - 目录/PNG/JSON三者绑定确认
- **审核引擎** - 三步审核（索引核对、尺寸核对、材料核对）
- **报告生成** - PDF和Excel格式审核报告

### 技术架构
- **前端**: React + Tailwind CSS + shadcn/ui，端口7001
- **后端**: Python + FastAPI，端口7000
- **AI识别**: Kimi API（Kimi Code订阅方案）
- **CAD数据提取**: AutoLISP插件 + pyautocad
- **PDF处理**: PyMuPDF
- **数据库**: SQLite本地部署

## Impact

- ** Affected specs **: 完整的室内装饰施工图审核系统
- ** Affected code **:
  - 后端: cad-review-backend/
  - 前端: cad-review-frontend/
  - 数据目录: ~/cad-review/

## ADDED Requirements

### Requirement: 项目管理系统
系统 SHALL 提供项目管理功能，支持创建、编辑、删除项目，并进行分类管理和标签管理。

#### Scenario: 创建新项目
- **WHEN** 用户在项目列表页点击"新建项目"按钮，填写项目名称、选择分类、添加标签后点击创建
- **THEN** 系统创建新项目，生成唯一项目ID，创建项目存储目录，返回成功消息

#### Scenario: 分类筛选
- **WHEN** 用户在左侧分类栏点击某个分类
- **THEN** 右侧项目列表只显示该分类下的项目

### Requirement: 目录识别系统
系统 SHALL 提供目录PNG图片上传和AI识别功能，用户可校对后锁定目录。

#### Scenario: 目录识别
- **WHEN** 用户上传目录PNG图片
- **THEN** 系统调用Kimi API识别目录内容，返回图号/图名/版本/日期列表，用户可编辑确认

#### Scenario: 目录锁定
- **WHEN** 用户确认目录内容正确后点击"确认目录"
- **THEN** 目录状态变为locked，后续操作以此目录为锚点

### Requirement: 图纸匹配系统
系统 SHALL 提供PDF上传、逐页转PNG、AI识别图名图号、自动匹配目录功能。

#### Scenario: PDF流式处理
- **WHEN** 用户上传PDF图纸文件
- **THEN** 系统逐页转换为PNG，调用Kimi识别每页图名图号，与目录自动匹配，实时推送进度

#### Scenario: 手动匹配
- **WHEN** 图纸未能自动匹配目录
- **THEN** 用户可通过下拉选择手动指定对应目录条目

### Requirement: DWG数据提取系统
系统 SHALL 提供DWG文件上传、AutoCAD数据提取、JSON生成功能，支持版本管理。

#### Scenario: DWG数据提取
- **WHEN** 用户上传DWG文件
- **THEN** 系统调用AutoCAD提取该文件所有布局的标注/索引/材料数据，每个布局生成一个JSON文件

#### Scenario: 版本管理
- **WHEN** 用户重新上传同一DWG文件
- **THEN** 旧版本保留，新版本标记为最新，系统提示建议重新审核

### Requirement: 三线匹配确认
系统 SHALL 提供目录/PNG/JSON三线匹配状态展示和确认功能。

#### Scenario: 三线匹配展示
- **WHEN** 用户进入三线匹配确认步骤
- **THEN** 系统展示每个目录条目对应的PNG和JSON状态，明确标识缺失项

### Requirement: 审核引擎
系统 SHALL 提供三步自动审核功能：索引核对、尺寸核对、材料核对。

#### Scenario: 索引核对
- **WHEN** 用户点击"开始审核"
- **THEN** 系统首先执行索引核对，检测断链和孤立索引问题

#### Scenario: 尺寸核对
- **WHEN** 索引核对完成后
- **THEN** 系统基于索引关系匹配平立面图，比对同一面墙的尺寸标注，检测不一致问题

#### Scenario: 材料核对
- **WHEN** 尺寸核对完成后
- **THEN** 系统比对材料表与图纸标注，检测未定义/未使用/名称不一致问题

### Requirement: 报告生成
系统 SHALL 提供PDF和Excel格式的审核报告下载。

#### Scenario: 下载PDF报告
- **WHEN** 用户点击"下载PDF"
- **THEN** 系统生成中文PDF报告，包含封面、问题概览、各类问题详情

#### Scenario: 下载Excel报告
- **WHEN** 用户点击"下载Excel"
- **THEN** 系统生成Excel报告，多Sheet分别展示各类问题，颜色标记严重程度

### Requirement: 数据缓存更新机制
系统 SHALL 提供数据版本管理和更新提醒功能。

#### Scenario: 数据更新提醒
- **WHEN** 用户重新上传目录/PDF/DWG后进入项目
- **THEN** 系统显示Alert提醒数据已更新，建议重新审核

## MODIFIED Requirements

### Requirement: 项目状态流转
项目状态按以下流程流转：
- new → catalog_locked → matching → ready → auditing → done

## REMOVED Requirements

### Requirement: 原有技术方案
**Reason**: 经过验证已被放弃的方案不再实现
- ezdxf解析DXF渲染图像
- ezdxf坐标映射到PNG
- AI直接读A1整图
- PDF提取文字
- AI读裁图
- APS云端AutoCAD
- pyautocad服务器部署

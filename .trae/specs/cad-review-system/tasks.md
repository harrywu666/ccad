# 任务清单：室内装饰施工图AI自动审核系统

## 开发阶段总览

| 阶段 | 名称 | 预估周期 |
|------|------|---------|
| 第零阶段 | 环境搭建与准备 | 1周 |
| 第一阶段 | 项目骨架搭建 | 1周 |
| 第二阶段 | 项目管理模块 | 1～2周 |
| 第三阶段 | 目录识别模块 | 1～2周 |
| 第四阶段 | PDF转PNG模块 | 1～2周 |
| 第五阶段 | CAD插件模块 | 2～3周 |
| 第六阶段 | 三线匹配模块 | 1周 |
| 第七阶段 | 审核引擎模块 | 3～4周 |
| 第八阶段 | 报告生成模块 | 1～2周 |
| 第九阶段 | 界面完善与测试 | 2周 |

---

# 任务列表

## 第零阶段：环境搭建与准备

- [ ] 任务0-1: 安装Python环境
  - [ ] 检查是否已安装Python 3.10+
  - [ ] 安装pyenv管理Python版本
  - [ ] 创建虚拟环境venv
  - [ ] 安装依赖：fastapi uvicorn pymupdf pillow openai sqlalchemy aiofiles python-multipart openpyxl reportlab websockets

- [ ] 任务0-2: 安装Node.js和创建React项目
  - [ ] 安装Node.js 18+（用nvm管理）
  - [ ] 创建React项目 cad-review-frontend
  - [ ] 安装并配置shadcn/ui组件库
  - [ ] 安装axios和react-router-dom
  - [ ] 配置前端运行端口为7001

- [ ] 任务0-3: 创建后端项目目录结构
  - [ ] 创建cad-review-backend目录
  - [ ] 创建main.py
  - [ ] 创建database.py
  - [ ] 创建models.py
  - [ ] 创建routers/目录及所有路由文件
  - [ ] 创建services/目录及所有服务文件
  - [ ] 创建utils/目录

- [ ] 任务0-4: 注册Kimi API
  - [ ] 创建.env文件配置KIMI_CODE_API_KEY

---

## 第一阶段：项目骨架搭建

- [ ] 任务1-1: 数据库初始化
  - [ ] 编写database.py创建SQLite数据库连接
  - [ ] 编写models.py定义所有ORM模型
  - [ ] 编写初始化函数创建所有表
  - [ ] 预置5个默认分类

- [ ] 任务1-2: FastAPI主入口（端口7000）
  - [ ] 创建FastAPI应用实例
  - [ ] 配置CORS
  - [ ] 注册所有router
  - [ ] 添加启动事件

- [ ] 任务1-3: 基础接口验证
  - [ ] 启动后端服务验证端口7000
  - [ ] 访问/docs验证API文档

---

## 第二阶段：项目管理模块

- [ ] 任务2-1: 分类管理接口
  - [ ] 实现GET /api/categories
  - [ ] 实现POST /api/categories
  - [ ] 实现PUT /api/categories/{id}
  - [ ] 实现DELETE /api/categories/{id}

- [ ] 任务2-2: 项目管理接口
  - [ ] 实现POST /api/projects
  - [ ] 实现GET /api/projects（支持筛选）
  - [ ] 实现GET /api/projects/{id}
  - [ ] 实现PUT /api/projects/{id}
  - [ ] 实现DELETE /api/projects/{id}

- [ ] 任务2-3: 缓存版本服务
  - [ ] 实现increment_cache_version()
  - [ ] 实现check_cache_version()

- [ ] 任务2-4: 前端项目列表页
  - [ ] 实现项目列表页面
  - [ ] 实现分类侧边栏
  - [ ] 实现新建项目弹窗
  - [ ] 实现分类管理弹窗

---

## 第三阶段：目录识别模块

- [ ] 任务3-1: 文件上传接口（含替换逻辑）
  - [ ] 实现POST /api/projects/{id}/catalog/upload

- [ ] 任务3-2: Kimi目录识别服务
  - [ ] 实现recognize_catalog()函数

- [ ] 任务3-3: 目录完整接口
  - [ ] 实现GET /api/projects/{id}/catalog
  - [ ] 实现PUT /api/projects/{id}/catalog
  - [ ] 实现POST /api/projects/{id}/catalog/lock
  - [ ] 实现DELETE /api/projects/{id}/catalog

- [ ] 任务3-4: 前端目录模块
  - [ ] 实现目录上传组件
  - [ ] 实现识别结果表格（可编辑）
  - [ ] 实现目录锁定功能

---

## 第四阶段：PDF转PNG模块

- [ ] 任务4-1: PDF转PNG服务
  - [ ] 实现pdf_to_pngs_stream()
  - [ ] 实现crop_region()
  - [ ] 实现create_thumbnail()

- [ ] 任务4-2: 图名图号识别
  - [ ] 实现recognize_sheet_info()

- [ ] 任务4-3: PDF上传接口（含替换逻辑）
  - [ ] 实现POST /api/projects/{id}/drawings/upload
  - [ ] 实现WebSocket进度推送

- [ ] 任务4-4: 前端图纸匹配页
  - [ ] 实现PDF上传组件
  - [ ] 实现进度显示
  - [ ] 实现匹配结果表格
  - [ ] 实现手动匹配功能

---

## 第五阶段：CAD插件模块

- [ ] 任务5-1: AutoLISP基础框架
  - [ ] 编写extract_data.lsp
  - [ ] 实现布局遍历功能

- [ ] 任务5-2: 单布局数据提取函数
  - [ ] 提取视口信息
  - [ ] 提取模型空间标注
  - [ ] 提取布局空间标注
  - [ ] 提取索引图块
  - [ ] 提取材料引线
  - [ ] 提取材料表

- [ ] 任务5-3: 按布局生成JSON文件
  - [ ] 实现write-layout-json()
  - [ ] 实现EXTRACTDATA命令

- [ ] 任务5-4: Python CAD服务
  - [ ] 实现extract_dwg_data()

- [ ] 任务5-5: DWG上传接口（多JSON版本管理）
  - [ ] 实现POST /api/projects/{id}/dwg/upload

- [ ] 任务5-6: 前端DWG管理页
  - [ ] 实现DWG上传组件
  - [ ] 实现数据展示
  - [ ] 实现版本历史

---

## 第六阶段：三线匹配模块

- [ ] 任务6-1: 三线汇合逻辑
  - [ ] 实现match_three_lines()

- [ ] 任务6-2: 前端三线确认页
  - [ ] 实现三列表格展示
  - [ ] 实现状态显示

---

## 第七阶段：审核引擎模块

- [ ] 任务7-1: 索引核对引擎
  - [ ] 实现audit_indexes()

- [ ] 任务7-2: 尺寸核对引擎
  - [ ] 实现audit_dimensions()

- [ ] 任务7-3: 材料核对引擎
  - [ ] 实现audit_materials()

- [ ] 任务7-4: 审核流程控制+历史记录
  - [ ] 实现POST /api/projects/{id}/audit/start
  - [ ] 实现GET /api/projects/{id}/audit/status
  - [ ] 实现GET /api/projects/{id}/audit/results
  - [ ] 实现GET /api/projects/{id}/audit/history

---

## 第八阶段：报告生成模块

- [ ] 任务8-1: PDF报告
  - [ ] 实现generate_pdf_report()

- [ ] 任务8-2: Excel报告
  - [ ] 实现generate_excel_report()

- [ ] 任务8-3: 前端报告页
  - [ ] 实现报告展示页面
  - [ ] 实现下载功能

---

## 第九阶段：界面完善与测试

- [ ] 任务9-1: 审核结果页
  - [ ] 实现结果概览
  - [ ] 实现问题列表展示

- [ ] 任务9-2: 数据更新提醒
  - [ ] 实现cache_version检查
  - [ ] 实现更新提醒Alert

- [ ] 任务9-3: 一键启动脚本
  - [ ] 编写start.sh（Mac）
  - [ ] 编写start.bat（Windows）

---

# 任务依赖关系

- 任务0-1 完成后才能进行 任务0-3
- 任务0-2 完成后才能进行 任务2-4 及后续前端任务
- 任务0-3 完成后才能进行 任务1-1
- 任务1-1 和 任务1-2 完成后才能进行 任务1-3
- 任务1完成后才能进行第二阶段
- 第二阶段完成后才能进行第三阶段
- 以此类推，按阶段顺序执行

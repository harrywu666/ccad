# 验收检查清单：室内装饰施工图AI自动审核系统

---

## 环境搭建验收

- [ ] Python 3.10+ 已安装，虚拟环境可正常激活
- [ ] 依赖包已安装：fastapi uvicorn pymupdf pillow sqlalchemy aiofiles python-multipart openpyxl reportlab websockets httpx
- [ ] Node.js 18+ 已安装
- [ ] React项目 cad-review-frontend 已创建
- [ ] shadcn/ui 已安装配置
- [ ] 前端端口配置为7001
- [ ] 后端目录 cad-review-backend 已创建
- [ ] .env 文件已创建，KIMI_CODE_API_KEY 已配置
- [ ] 后端端口配置为7000

---

## 项目骨架验收

- [ ] SQLite数据库 ~/cad-review/db/database.sqlite 已创建
- [ ] 所有数据表已创建：projects, project_categories, catalog, drawings, json_data, audit_results
- [ ] 5个默认分类已预置：住宅、商业、办公、酒店、其他
- [ ] FastAPI应用在7000端口可启动
- [ ] 访问 http://localhost:7000/docs 可看到API文档
- [ ] CORS配置正确，前端7001可访问后端API

---

## 项目管理模块验收

- [ ] 可以创建新项目（填写名称、分类、标签）
- [ ] 项目列表可显示，按分类筛选正常
- [ ] 搜索项目功能正常
- [ ] 分类管理（新增/修改/删除）正常
- [ ] 删除项目会同时删除所有关联数据和文件
- [ ] cache_version机制正常工作

---

## 目录识别模块验收

- [ ] 上传目录PNG图片成功保存到 ~/cad-review/projects/{id}/catalog/
- [ ] Kimi API调用成功，返回识别结果
- [ ] 目录表格可编辑，图号/图名/版本/日期可修改
- [ ] 确认目录后状态变为locked，不可编辑
- [ ] 重新上传目录会替换旧数据
- [ ] 前端显示目录识别进度

---

## PDF转PNG模块验收

- [ ] PDF上传成功保存
- [ ] 逐页转换为300DPI PNG
- [ ] 每页调用Kimi识别图名图号
- [ ] 与目录自动匹配
- [ ] WebSocket推送实时进度
- [ ] 重新上传PDF会保留旧版本
- [ ] 未匹配图纸可手动选择目录条目

---

## CAD插件模块验收

- [ ] AutoLISP脚本可执行
- [ ] DWG文件可提取数据，按布局生成JSON
- [ ] JSON包含dimensions、indexes、materials、material_table
- [ ] Python服务可调用AutoCAD
- [ ] 多JSON版本管理正常
- [ ] 重新上传DWG保留历史版本

---

## 三线匹配模块验收

- [ ] 三线匹配状态正确展示
- [ ] 目录/PNG/JSON三者绑定关系正确
- [ ] 缺失数据明显标识

---

## 审核引擎模块验收

- [ ] 三步审核可顺序执行
- [ ] 索引核对：检测断链和孤立索引
- [ ] 尺寸核对：平立面尺寸比对，输出数值差异
- [ ] 材料核对：检测未定义/未使用/名称不一致
- [ ] 每条问题有自然语言描述
- [ ] 审核进度实时推送
- [ ] 历史审核记录可查询

---

## 报告生成模块验收

- [ ] PDF报告可下载，封面/概览/详情格式正确
- [ ] Excel报告可下载，多Sheet颜色标记正确
- [ ] 支持按历史版本导出

---

## 前端界面验收

- [ ] 项目列表页：分类侧边栏+卡片网格+搜索筛选
- [ ] 新建项目弹窗功能完整
- [ ] 项目详情页：五步骤导航正确
- [ ] 目录上传和识别结果展示
- [ ] PDF上传和匹配结果展示
- [ ] DWG上传和数据展示
- [ ] 三线匹配确认页
- [ ] 审核结果页：概览+三类问题Tab切换
- [ ] 数据更新提醒Alert显示
- [ ] 响应式布局正常

---

## 系统整体验收

- [ ] 完整流程可跑通：新建项目→上传目录→上传PDF→上传DWG→三线匹配→审核→报告
- [ ] 项目状态流转正确
- [ ] 数据替换机制正常工作
- [ ] 缓存刷新机制正常工作
- [ ] 本地数据存储路径正确

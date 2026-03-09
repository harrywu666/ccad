# 文档五：Trae Vibe Coding 操作手册
## 专为零代码基础的室内设计师准备

**版本：V1.0 | 日期：2026年2月**

---

## 一、写在前面

你不需要学会编程，但你需要学会「跟AI说清楚你要什么」。

作为室内设计师，你最大的优势是：你比任何程序员都更清楚图纸审核的业务逻辑。把这个优势发挥出来，就是Vibe Coding的核心。

这份手册告诉你：
- 怎么装Trae，怎么用
- 怎么写Prompt让AI写出正确的代码
- 遇到报错怎么处理
- 常见坑和怎么避开

---

## 二、安装和配置Trae

### 2.1 下载安装

1. 访问 **trae.ai**
2. 下载Mac版本（Apple Silicon或Intel，根据你的Mac选择）
3. 拖到Applications文件夹安装
4. 打开Trae，用邮箱注册账号

### 2.2 打开你的项目

1. 在Trae中点击「Open Folder」
2. 选择你的项目文件夹（cad-review-backend 或 cad-review-frontend）
3. 左侧会显示项目的文件树

### 2.3 认识Trae的界面

```
┌──────────────────────────────────────────┐
│  文件树  │         代码编辑区             │
│          │                               │
│ 📁src    │  // 代码在这里显示和编辑        │
│ 📄main.py│                               │
│ 📄...    ├───────────────────────────────┤
│          │         AI对话区               │
│          │  你在这里输入Prompt            │
│          │  AI在这里回复代码              │
└──────────┴───────────────────────────────┘
```

### 2.4 开始一次AI对话

1. 点击右侧的AI对话区（或按快捷键 Cmd+L）
2. 在输入框里输入你的需求
3. 按Enter发送
4. AI会回复代码，并解释它做了什么
5. 点击「Apply」或「Accept」将代码应用到文件

---

## 三、怎么写好Prompt

这是最重要的一节。写Prompt就像给施工队交底图纸，越详细越准确，返工越少。

### 3.1 Prompt的基本结构

```
【背景】这个文件/函数是干什么的
【任务】我要你做什么
【具体要求】
  - 要求1
  - 要求2
  - 要求3
【注意事项】要避免的问题
```

### 3.2 好的Prompt vs 坏的Prompt

**❌ 坏的Prompt（太模糊）：**
```
帮我写一个上传文件的功能
```

**✅ 好的Prompt（清晰具体）：**
```
帮我在FastAPI的routers/catalog.py中实现文件上传接口：
POST /api/projects/{project_id}/catalog/upload
要求：
1. 接收PNG或JPG图片文件上传（用UploadFile类型）
2. 验证文件类型，不是图片就返回400错误
3. 将文件保存到 ~/cad-review/projects/{project_id}/catalog/ 目录
4. 目录不存在时自动创建
5. 返回格式：{"success": true, "data": {"filename": "xxx.png", "path": "..."}}
```

---

**❌ 坏的Prompt（一次要太多）：**
```
帮我实现整个审核系统的后端
```

**✅ 好的Prompt（一次一个函数）：**
```
帮我写一个Python函数 recognize_catalog(image_path)
这个函数的作用是调用Kimi API识别图纸目录：
1. 读取image_path指向的图片文件
2. 转为base64格式
3. 调用Kimi Code API（base_url 使用 https://api.kimi.com/coding/v1）
4. Prompt是："这是一张室内装饰施工图的图纸目录..."（具体内容见文档）
5. 解析返回的JSON
6. 返回列表格式的识别结果
API Key从环境变量KIMI_CODE_API_KEY读取
```

### 3.3 发挥你的设计师优势

在描述业务逻辑时，用你熟悉的专业语言：

```
好的描述方式：
"索引符号是CAD图纸中的圆形图块，通常圆内上方写着索引编号如①②③，
 下方写着对应图纸的图号如A2-01，图块名通常包含'索引'或'INDEX'字样"

不好的描述方式：
"帮我识别CAD里的圆形符号"
```

### 3.4 当AI理解错了

重新发一条消息，更具体地纠正：

```
不对，我说的不是XXX，我说的是YYY。
具体来说：
...（重新描述清楚）
```

不要直接修改AI的代码，让AI重新生成。

---

## 四、每次开始新任务的标准流程

### Step 1：新建对话
每个新任务开始一个新的Trae对话，不要在同一个对话里做太多不同的事。

### Step 2：给AI背景
把相关的文件内容分享给AI：
- 在Trae中用 @ 符号引用文件，例如输入 @database.py
- AI会读取这个文件的内容作为上下文

### Step 3：描述任务
按照Prompt规范描述你的需求。

### Step 4：让AI先解释思路
在发送代码请求之前，先问一句：
```
在你写代码之前，先告诉我你的实现思路，我确认没问题再让你写代码
```

### Step 5：审查代码
AI生成代码后，不要急着Apply，先看一眼：
- 函数名和变量名是不是你理解的那个意思
- 有没有TODO或未完成的部分
- 有没有`pass`（表示空函数体）

### Step 6：Apply并测试
确认代码看起来没问题，点Apply，然后运行测试。

---

## 五、怎么运行和测试代码

### 5.1 运行Python后端

在Trae底部打开Terminal（终端）：

```bash
# 进入项目目录
cd cad-review-backend

# 激活虚拟环境
source venv/bin/activate

# 启动服务
uvicorn main:app --reload --port 8000
```

看到这行说明启动成功：
```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### 5.2 用浏览器测试API

打开浏览器，访问：
```
http://localhost:8000/docs
```
这是FastAPI自动生成的API文档，可以在网页上直接测试每个接口。

### 5.3 运行React前端

打开新的Terminal标签：
```bash
cd cad-review-frontend
npm start
```

浏览器会自动打开 http://localhost:3000

---

## 六、遇到报错怎么办

### 6.1 标准处理流程

```
出现报错
    ↓
完整复制报错信息
    ↓
在Trae中新开一条消息，输入：
"我运行代码时遇到了报错，报错信息如下：
[粘贴完整报错]
这是在执行什么操作时出现的：[描述你做了什么]
请帮我分析原因并修复"
    ↓
AI给出修复方案
    ↓
Apply并重新测试
```

### 6.2 常见报错类型

**ModuleNotFoundError（找不到模块）：**
```
报错：ModuleNotFoundError: No module named 'fitz'
解决：告诉AI这个报错，AI会告诉你安装命令
通常是：pip install pymupdf
```

**Port already in use（端口被占用）：**
```
报错：ERROR: [Errno 48] Address already in use
解决：关掉之前运行的服务，或换一个端口
命令：lsof -ti:8000 | xargs kill -9
```

**JSON解析错误：**
```
报错：json.JSONDecodeError
解决：Kimi返回的内容不是纯JSON，需要清理
告诉AI这个报错，让它在解析前先清理markdown代码块标记
```

**CORS错误（前端无法访问后端）：**
```
报错：Access to XMLHttpRequest has been blocked by CORS policy
解决：检查FastAPI的CORS配置，确保允许了前端的域名
把报错发给AI，让它检查main.py的CORS设置
```

### 6.3 当AI的修复不管用

```
"你给的修复方案还是有问题，报错信息变成了：
[新的报错]
请换一种思路来解决"
```

如果连续三次修复都不成功：
```
"我们换一种思路，不用[当前方案]，
改用[另一种方案，如果你知道的话]来实现同样的功能"
```

---

## 七、代码管理：用Git保存进度

### 7.1 为什么要用Git

Git就像「图纸版本管理」，你每完成一个功能，就保存一个版本。如果后来改坏了，可以随时回到之前的版本。

### 7.2 基本Git命令

在Trae的Terminal中：

```bash
# 第一次初始化（只做一次）
git init
git add .
git commit -m "初始化项目"

# 每次完成一个功能后保存
git add .
git commit -m "完成目录识别功能"

# 查看历史版本
git log --oneline

# 回到某个版本（如果改坏了）
git checkout [版本号前6位]
```

### 7.3 什么时候commit

每完成开发计划中的一个任务就commit一次，命名规范：
```
完成任务1-1：插件框架搭建
完成任务2-3：目录识别完整接口
修复：目录识别JSON解析错误
```

---

## 八、跟Trae沟通的进阶技巧

### 8.1 让AI检查已有代码

```
请检查 @services/kimi_service.py 这个文件，
有没有潜在的问题或可以改进的地方？
```

### 8.2 让AI解释代码

```
请用简单的语言解释这段代码是做什么的：
[粘贴代码]
不需要技术细节，告诉我它做了什么事情就好
```

### 8.3 让AI写测试

```
帮我为这个函数写一个简单的测试：
@services/pdf_service.py 中的 pdf_to_pngs_stream 函数
测试内容：用一个1页的测试PDF，验证能正确输出PNG
```

### 8.4 让AI重构代码

当一段代码已经写出来但感觉很乱：
```
这段代码能正确运行，但感觉很乱，请帮我重构一下，
让它更清晰易读，但不改变功能：
[粘贴代码]
```

---

## 九、Kimi API使用说明

> ⚠️ **本项目用的是 Kimi Code 订阅方案，不是 Moonshot 开放平台。
> 端点、Key格式、模型名都不同，不能混用。**

### 9.1 三个关键配置（必须记住）

```python
端点：https://api.kimi.com/coding/v1      # ❌ 不是 api.moonshot.cn
模型：k2p5                                # ❌ 不是 kimi-k2.5 / moonshot-v1-8k
UA：  claude-code/1.0                     # 必须加，否则返回 403
```

### 9.2 获取 API Key

1. 打开 Kimi Code 客户端或 VSCode 插件
2. 登录账号 → 设置 → 找到 API Key（格式：`sk-kimi-xxxxxxx`）
3. 保存到项目根目录的 `.env` 文件：
```
KIMI_CODE_API_KEY=sk-kimi-你的密钥
```

### 9.3 不需要自己写调用代码

项目中已有 `services/kimi_service.py`，里面的 `call_kimi()` 函数封装了所有细节。
你只需要调用这个函数，传入 Prompt 和图片即可：

```python
# 发一张图片
result = await call_kimi(
    system_prompt="你是室内装饰施工图识别专家，只返回JSON。",
    user_prompt="提取图纸目录内容...",
    images=[png_bytes],          # bytes列表
)

# 发多张图片
result = await call_kimi(
    system_prompt="你是审图专家，只返回JSON。",
    user_prompt=f"比对以下平立面尺寸：{json_data}",
    images=[plan_thumb, plan_crop, elev_thumb, elev_crop],
)

# 纯文字（不带图片）
result = await call_kimi(
    system_prompt="你是材料命名专家，只返回JSON。",
    user_prompt='判断"仿古砖"和"仿古地砖"是否同一材料',
)
```

`call_kimi()` 返回的已经是解析好的 Python 字典或列表，不需要再做 JSON 解析。

### 9.4 写Prompt的注意事项

**在 system_prompt 里声明只返回JSON：**
```
"你是室内装饰施工图识别专家，只返回JSON格式，不要任何解释，不要markdown代码块。"
```

**不用自己处理JSON解析**，`call_kimi()` 内部的 `_parse_json()` 已经处理了：
- AI直接返回JSON ✅
- AI返回被代码块包裹的JSON ✅
- AI返回带解释文字的JSON ✅

### 9.5 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| 403 错误 | 缺少 User-Agent 或端点用错 | 检查 kimi_service.py 配置 |
| 401 错误 | API Key 格式不对或端点用的是 moonshot | 确认用 `api.kimi.com/coding/v1` |
| JSON解析失败 | max_tokens太小，JSON被截断 | kimi_service.py 已设65536，检查是否被改动 |
| 识别结果不稳定 | temperature太高 | kimi_service.py 默认0.1，不要改大 |

### 9.6 控制成本

- 图片在发送前缩小到800px宽以内（用 `create_thumbnail()` 函数）
- 开发调试阶段用小图测试，确认逻辑正确再用真实图纸
- 订阅制不按Token计费，但要避免无意义的重复调用

---

## 十、开发阶段的注意事项

### 10.1 数据安全
- DWG文件包含设计方案，不要上传到公网
- 本系统是本地部署，数据不离开用户电脑，这是设计优势

### 10.2 AutoCAD相关（需要Windows）
- CAD插件开发和测试必须在Windows电脑上进行
- 如果你用Mac，用Parallels虚拟机跑Windows
- AutoLISP文件就是普通文本文件（.lsp扩展名），在Mac上写好再放到Windows里测试

### 10.3 开发顺序很重要
- 严格按照开发计划的阶段顺序来
- 每个阶段完成后验证通过才进入下一阶段
- 不要跳步，后面的功能依赖前面的基础

### 10.4 遇到卡壳怎么办
如果一个问题折腾了超过30分钟还没解决：
1. 把问题描述清楚（做了什么、出现了什么、期望什么）
2. 换一个角度问AI：「有没有更简单的方法实现同样的功能？」
3. 把问题拆得更小：先让最核心的那一步跑通，再扩展
4. 休息一下，往往回来后思路更清晰

---

*Trae Vibe Coding操作手册 V1.0 | 2026年2月*

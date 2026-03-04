# Windows AutoCAD 2024 集成说明

## 1. 目标

后端已支持以下链路：

- 批量上传多个 DWG
- 通过 AutoCAD COM 后台自动打开 DWG
- 加载 LISP 插件按布局导出 JSON（一个布局一个 JSON，跳过 Model）
- 将布局 JSON 自动匹配到目录图纸并写入 `json_data`

对应代码：

- COM 自动化：`services/autocad_com_service.py`
- CAD 服务：`services/cad_service.py`
- DWG 路由：`routers/dwg.py`
- LISP 插件：`cad_plugins/extract_layout_json.lsp`

## 2. Windows 环境准备

1. 安装 AutoCAD 2024（已激活可打开 DWG）。
2. 安装 Python 3.10+。
3. 安装依赖：

```bash
pip install pywin32 fastapi uvicorn sqlalchemy python-multipart
```

4. 启动后端（7000）：

```bash
uvicorn main:app --reload --port 7000
```

## 3. 字体丢失弹窗处理（已内置）

为减少“缺少字体/SHX/代理信息”阻塞，COM 自动化已做：

- `FILEDIA=0`、`CMDDIA=0`（关对话框）
- `PROXYNOTICE=0`
- `FONTALT=txt.shx`
- 弹窗监视线程自动关闭 `#32770` 对话框（标题包含 font/missing/字体/缺少 等关键词）

如果你本机仍有特殊字体弹窗，可再补充：

- 把常用 SHX/TTC 放入 AutoCAD 支持路径
- 在 AutoCAD 选项里设置替代字体

## 4. 插件导出约定

LISP 插件函数（由 COM 调用）：

```lisp
(ccad:export-layout-json "D:/out/jsons" "D:/out/jsons/demo.__done__.flag")
```

输出 JSON 命名：

- `{dwg_stem}_{layout_name}.json`

输出字段（当前版本）：

- `source_dwg`
- `layout_name`
- `sheet_no`
- `sheet_name`
- `viewports`（`VIEWPORT`：位置、比例、激活图层等）
- `dimensions`
- `pseudo_texts`（`TEXT/MTEXT` 纯数字伪标注）
- `indexes`
- `title_blocks`（`INSERT` 图签块属性）
- `materials`
- `material_table`
- `layers`

## 5. 批量提取测试（Windows）

可先不走前端，直接跑脚本验证 COM：

```bash
python utils/test_autocad_com_extract.py --dwg-dir D:\dwgs --out-dir D:\jsons
```

如果要走接口批量上传，调用：

- `POST /api/projects/{id}/dwg/upload`（`files` 可传多个 `.dwg`）

返回包含：

- `summary.layouts_total`（总布局数）
- `summary.matched/unmatched`
- 每个布局的 `sheet_no/layout_name/json_path/data_version`

## 6. 自定义外部命令（可选）

如你已有独立提取器，可设置环境变量覆盖内置 COM：

```bash
set CAD_PLUGIN_EXTRACTOR_CMD=python D:/tools/my_extractor.py --dwg "{dwg}" --out "{outdir}"
```

后端会按该命令执行，并从输出目录收集 `{dwg_stem}_*.json`。

# PROJECT_STATUS

## 项目概述

CyberReel — Python 3.12+ 媒体库管理工具（NiceGUI 3.13.0 + SQLite + PyAV），支持多 Profile 媒体扫描、同步、截图采集、文件重命名。

## 技术栈

- **后端**: Python 3.12, NiceGUI 3.13.0, SQLite (sqlite3.Row), PyAV
- **前端**: NiceGUI 组件 (ui.dialog, ui.row, ui.card 等), Tailwind CSS, HTML5
- **存储**: data.db (SQLite), profiles_config.json

## 文件结构

```
cyber_reel/
├── main.py                     # 入口，初始化 ConfigManager/Database/Registry → create_layout
├── config_manager.py           # Profile 配置管理，读写 profiles_config.json
├── db.py                       # SQLite 统一封装 (Database 类)，thread-local 连接
├── profiles_config.json        # 各 Profile 的 root/from/to/naming_rules/table_schema/screenshot_config
├── data.db                     # SQLite 数据库 (media_{profile}, screenshots, rename_history)
├── create_test_db.py           # 测试数据生成脚本
├── profiles/
│   ├── __init__.py             # ProfileBase 基类 + ProfileRegistry + 截图采集 (PyAV)
│   ├── movie/handler.py        # class MovieHandler(ProfileBase): pass (dict 映射)
│   ├── tv/handler.py           # class TVHandler(ProfileBase): pass (dict 映射)
│   ├── realshot/handler.py     # class RealshotHandler(ProfileBase): pass (dict 映射)
│   └── homework/handler.py     # HomeworkHandler — 重写 normalize() 使用 regex 替换
├── ui/
│   ├── layout.py               # 主布局：左侧抽屉菜单 + 右侧内容区
│   ├── state.py                # 全局共享状态 (避免循环导入)
│   ├── home.py                 # 首页
│   ├── config_page.py          # 配置页：Profile 切换 + root/from/to + schema + 截图配置
│   ├── sync_page.py            # 同步页：DB同步 + 截图采集 + 文件重命名 + 回滚
│   ├── browser_page.py         # 媒体浏览器（懒加载封面 + 截图）
│   └── tools_page.py           # 工具页（参数输入 + 黑底白字配色）
├── tools/
│   └── scan_root.py            # 列出指定目录下所有视频文件
└── static/css/cyberpunk.css
```

## 数据表

| 表名 | 用途 |
|---|---|
| `media_{profile}` | 每种 Profile 独立的媒体表（movie/tv/realshot/homework） |
| `screenshots` | 截图 BLOB 存储，关联 mv_path |
| `rename_history` | 文件重命名历史，支持 rollback |

基础列 (id/title/mv_path/cover/added_time) 始终存在，扩展列由 table_schema 配置定义。

## 路径三要素

| 路径 | 语义 |
|---|---|
| `root` | 已整理视频目录，DB 同步 + 浏览器展示均扫描此目录 |
| `from` | 原始新视频目录，rename 的源 |
| `to` | 更名后目标目录，rename 的目标，rollback 的源 |

排除逻辑：from/to 若在 root 下，同步/浏览器自动排除对应子目录。

## 已解决的问题

### 1. 媒体浏览器空白 — Path.resolve() 在 UNC 路径失败

**根因**: `Path.resolve()` 在 Windows 上会访问文件系统。对于 `\\TRUENAS\rust_bytes：电影` 这类 UNC 网络路径，网络不可达时 resolve 失败，导致所有记录被过滤掉。
**修复**: 用 `os.path.normpath()` + `.lower()` 做纯字符串路径比较，不碰文件系统。
**涉及文件**: `ui/browser_page.py`, `ui/sync_page.py`

### 2. from/to 目录下的视频混入浏览器

**根因**: `startswith(root)` 过滤太宽，root 下的 from/to 子目录未能排除。
**修复**: 新增 `_get_exclude_dirs()` 函数，计算 from/to 在 root 下的相对路径前缀，然后对每条记录做前缀排除。
**涉及文件**: `ui/browser_page.py` (与 sync_page.py 中同名函数独立)

### 3. 缩略图不可读 → 截图查看按钮

**变更**: 页面上不再渲染 28×38 的小缩略图，改为 `📷 N` 按钮，点击弹出截图浏览对话框。
**涉及文件**: `ui/browser_page.py` → `_render_shot_btn()`

### 4. 截图弹窗太窄 + 点击放大不生效

**修复**:
- 弹窗宽度: 用 `_style["min-width"] = "50vw"` / `"max-width" = "80vw"` 替代 `max-w-4xl` 类
- 点击放大: HTML `<dialog>` 在 NiceGUI 中不可靠，改为 `ui.dialog()` 组件，每个截图卡片有 🔍 按钮打开放大对话框 (`60vw-95vw`)
**涉及文件**: `ui/browser_page.py`

### 5. 移除折叠组 → 平铺表格

**变更**: 删除 `_render_group()` (ui.expansion 折叠)，改为 `_render_flat_table()` 平铺显示，按路径分组显示 `▸ parent/path` 分隔行。
**涉及文件**: `ui/browser_page.py`

### 6. 表头丢失（移除折叠组后的回归）

**根因**: `_render_group()` 内含表头行 (Cover/Title/动态列/Shots)，替换为 `_render_flat_table()` 时忘记补表头。
**修复**: 在 `_render_flat_table()` 顶部添加表头行，使用 flex 布局与数据行对齐。
**涉及文件**: `ui/browser_page.py`

### 7. Root 与数据库路径不匹配 → 回退显示

**根因**: DB 中测试数据路径为 `D:/Media/Movies/...`，配置的 root 为 `\\TRUENAS\rrust_bytes：电影`，normpath 后两者完全不匹配，所有记录被过滤，显示"暂无媒体数据"。
**修复**: root 过滤后若结果为空，回退显示全部记录，并在顶部黄色提示 `⚠ Root 不匹配任何记录，显示全部 N 条`。
**涉及文件**: `ui/browser_page.py`

### 8. 表格完全不渲染 — sqlite3.Row 无 .get() 方法

**根因**: `sorted(records, key=lambda r: r.get("title", ""))` — `sqlite3.Row` 没有 `.get()` 方法 (只有 `.keys()` 和 `[]`)，排序时抛出 `AttributeError`，后续表头和数据行全部未渲染。用户看到"共 N 条记录"但下方无表格。
**修复**: 改为 `r["title"] or ""`。
**涉及文件**: `ui/browser_page.py`

### 9. 截图采集全部"无法打开视频" — NameError: name 'moments' is not defined

**根因**: `_resolve_time_points()` 参数从 `moments` 重命名为 `times`，但函数体内仍引用旧名称 `moments`，导致所有视频截图均失败。
**修复**: 函数体内所有 `moments` 引用改为 `times`。
**涉及文件**: `profiles/__init__.py` → `_resolve_time_points()`

### 10. 大量视频"截取 0/1 张" — duration=0 时只取 [0.0]

**根因**: 视频时长未知时（duration=0.0），`_resolve_time_points()` 只返回 `[0.0]` 作为时间点，0.0 秒处通常为黑帧，PyAV 解码失败。
**修复**: 时长未知时使用几何级数偏移量 fallback: `[5.0, 30.0, 120.0, 600.0, 1800.0]`，确保覆盖不同时间段。
**涉及文件**: `profiles/__init__.py` → `_resolve_time_points()`

### 11. 质量重试太激进 — 有效帧被误弃

**根因**: 帧大小 <800KB 即丢弃并重试；duration=0 时所有重试指向同一时间点；重试结果直接被替换。
**修复**:
- `_retry_quality_frame()` 返回最佳帧而非最后帧，只在 retry 帧更大时才替换
- duration=0 时使用更宽随机偏移（±30s 而非 ±5%）
- 找到 ≥800KB 帧则提前返回
**涉及文件**: `profiles/__init__.py` → `_retry_quality_frame()`, `capture_one_video()`

### 12. 3 个视频 UnicodeDecodeError — PyAV 无法解码损坏容器

**根因**: 部分视频文件容器损坏或编码不兼容，PyAV 无法打开（即使用 ASCII 路径复制到临时文件）。
**处理**: 捕获异常后在状态信息中保留实际错误消息，不阻塞后续文件。55/58 成功截取，3 个无法修复。
**涉及文件**: `profiles/__init__.py` → `capture_one_video()`

### 13. 媒体浏览器性能优化 — 懒加载封面和截图

**根因**: 页面加载时一次性读取所有封面 BLOB 和截图 BLOB，导致页面打开缓慢。
**修复**:
- 封面：添加"📷 加载封面"按钮，初次渲染使用占位符，点击后才加载 BLOB
- 截图：只查询截图数量显示为按钮，点击按钮时才从 DB 加载截图并渲染弹窗
- 截图展示不再使用 PIL resize，改用 CSS `width:200px;height:150px;object-fit:contain`
**涉及文件**: `ui/browser_page.py` → `build_browser()`, `_render_flat_table()`, `_render_media_row()`, `_render_shot_btn()`

### 14. "加载封面"按钮位置错误 — 在表格下方而非上方

**根因**: `table_container` 在按钮行之前创建，NiceGUI DOM 顺序导致按钮渲染在表格下方。
**修复**: 延迟创建 `table_container`，在按钮行之后 `render_table()` 时才创建。
**涉及文件**: `ui/browser_page.py` → `build_browser()`

### 15. 命名规则架构统一 — Movie/TV 用 dict，Homework 用 regex

**需求**: Movie/TV 只需简单字符串替换 `{"A": "B"}`，Homework 需要正则 `sub(pattern, replacement)`。
**设计**:
- `ProfileBase.normalize()` 提供默认 dict 替换实现（遍历 naming_rules 做 `str.replace`）
- `HomeworkHandler.normalize()` 重写，读取 naming_rules 中的 pattern/replacement 做 regex
- MovieHandler/TVHandler/RealshotHandler 仅 `class XxxHandler(ProfileBase): pass`
**关键细节**: `normalize()` 使用 `f.name`（含扩展名）而非 `f.stem`，与用户配置的 key 对齐（用户配置 key 可能含 `.mkv` 等扩展名）。
**涉及文件**: `profiles/__init__.py`, `profiles/homework/handler.py`, `profiles/movie/handler.py`, `profiles/tv/handler.py`, `profiles/realshot/handler.py`

### 16. 重命名移动了所有文件 — 即使文件名未变化

**根因**: `_run_rename()` 将 normalize 的完整 mapping 传给 `rename()`，即使新旧文件名相同也被处理。
**修复**: 在调用 `rename()` 前过滤: `{p: n for p, n in raw_mapping.items() if p.name != n}`，空 mapping 时提前返回。
**涉及文件**: `ui/sync_page.py` → `_run_rename()`

### 17. 回滚架构重新设计 — 批次回滚 + 日期范围回滚

**需求**: 
- "回滚上一批"：回滚最近一次点击"文件名更新"后的所有记录（同一时间窗口内的全部）
- "批量回滚"：按日期范围选择，回滚从哪天到哪天的所有更名记录
- 修复原"全部回滚"路径错误问题

**实现**:
- DB 新增 `get_last_batch(profile, window_sec=5)` — 最近一条 ±5s 内的所有记录
- DB 新增 `get_rename_by_date_range(profile, start_date, end_date)` — SQL `date(timestamp) BETWEEN ? AND ?`
- DB 新增 `delete_rename_records(ids)` — 批量删除
- ProfileBase 新增 `rollback_records()`, `rollback_last_batch()`, `rollback_date_range()`
- 回滚时使用 `source_dir`（from 目录）作为还原目标，而非记录的原始 path
- 日期选择器最终使用 `ui.input(props="type=date")` 调用 HTML5 原生日期选择器（弹出样式，不占空间）
**涉及文件**: `db.py`, `profiles/__init__.py`, `ui/sync_page.py`

### 18. 工具页重新设计 — 参数输入 + 黑底白字

**需求**: 
- 工具页需要能传参给脚本
- 源码、参数、运行结果区域改为黑底白字配合

**实现**:
- 在源码区和运行结果区之间添加参数输入框
- 若参数非空，替换默认 root 作为 argv[1:]；若留空，使用 Profile root 作为默认参数
- 注入 `<style>` 覆盖 Quasar 内部样式：`.q-field__native`, `.q-field__control` 设 `background:#000 !important; color:#ddd !important`
- 选择脚本时清空参数和结果区
**涉及文件**: `ui/tools_page.py`

### 19. scan_root.py 简化

**需求**: 工具脚本只需要一个函数，打印指定路径下所有视频文件。
**实现**: 单文件单函数，`rglob("*")` 递归扫描，筛选视频扩展名后输出。
**传参示例**: 在工具页的参数区填 `"\\TRUENAS\rust_bytes：电影\new"`（含引号），脚本接收 `sys.argv[1]`。
**涉及文件**: `tools/scan_root.py`

## 关键设计决策

### 路径比较策略
- **禁止**: `Path.resolve()` — Windows 上会访问文件系统，UNC 路径/断网时失败
- **使用**: `os.path.normpath()` + `.lower()` — 纯字符串操作，不依赖 IO
- **排除逻辑**: 计算 from/to 在 root 下的相对前缀，而非简单字符串匹配

### 截图展示策略
- **不渲染**缩略图在列表页（节省带宽 + 避免布局问题）
- **按钮触发**对话框浏览（50vw-80vw）
- **二次放大**对话框查看原图（60vw-95vw）
- 所有截图 BLOB 转 base64 内嵌 HTML `<img>` 标签
- 不使用 PIL/Pillow 做浏览器端处理（CSS `object-fit:contain` 替代 resize）

### 截图采集策略
- 指定时间点 `times` 非空时按指定点截取，忽略 `count`
- 时长已知：均分 duration/(count+1)
- 时长未知：fallback 几何级数偏移 [5, 30, 120, 600, 1800]
- 非指定时间点：质量检查（<800KB 重试），重试帧仅在大於原帧时替换
- 每个视频上限=count，已有截图达到上限则跳过

### 命名规则架构
- Movie/TV/Realshot：`naming_rules = {"key": "value"}` → `str.replace(key, value)`
- Homework：`naming_rules = {"pattern": "...", "replacement": "..."}` → `re.sub(pattern, replacement)`
- normalize() 使用 `f.name`（含扩展名），与用户配置 key 对齐
- 仅重命名名字实际变化的文件 `p.name != new_name`

### 重命名策略（两阶段 UUID）
1. 全部文件 → UUID.扩展名（零冲突，同目录内）
2. UUID.扩展名 → 规范名（可选移动到 target_dir）
- 同名保护：已存在则追加 `_1`, `_2` 后缀
- 所有操作记录到 rename_history 表

### 回滚策略
- 按批次：取最近一条记录的 timestamp，±5s 窗口内的所有记录为一"批"
- 按日期范围：`date(timestamp) BETWEEN ? AND ?`，使用 HTML5 原生日期选择器
- 还原到 source_dir（from 目录）而非记录的 path
- 文件不存在时清除历史记录

### NiceGUI 注意事项
- `ui.html()` 中的 HTML `<dialog>` + `onclick` 不可靠，用 `ui.dialog()` 组件
- `sqlite3.Row` 只支持 `[]` 和 `.keys()`，不支持 `.get()`
- 弹窗宽度用 `_style["min-width"]` / `_style["max-width"]` 而非 Tailwind 类
- `ui.row()` 内的 `style("flex: N;")` 用于列宽对齐
- Quasar 内部样式需 `<style>` + `!important` 覆盖
- HTML5 原生日期选择器：`ui.input().props("type=date")` 替代 `ui.date()`（更紧凑）

### 项目重启命令
```bash
# 找到端口 PID
cmd //c "netstat -ano | findstr 8080 | findstr LISTENING"
# 杀掉进程
cmd //c "taskkill /PID <pid> /F"
# 启动
python main.py &
```
注意：Git Bash 中 `taskkill /PID` 会被解析为路径，需用 `cmd //c "taskkill /PID ..."` 包装。

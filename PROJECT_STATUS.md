# PROJECT_STATUS

## 项目概述

CyberReel — Python 3.14 媒体库管理工具（NiceGUI 3.14 + SQLite + PyAV），支持多 Profile 媒体扫描、同步、截图采集、文件重命名与回滚。

## 技术栈

- **后端**: Python 3.14, NiceGUI 3.14（requirements 宽松 `nicegui>=1.4`）, SQLite (`sqlite3.Row`), PyAV (`av`), Pillow
- **前端**: NiceGUI 组件 (ui.card/row/dialog/radio 等), Tailwind CSS, HTML5
- **存储**: `data.db` (SQLite), `profiles_config.json`

## 架构分层

| 层 | 目录 | 职责 |
|---|---|---|
| 入口 | `main.py` | 初始化 ConfigManager/Database/Registry → create_layout |
| 配置 | `config_manager.py` | Profile 配置读写（profiles_config.json） |
| 核心后端 | `core/` | 与 UI 无关的纯逻辑（db/files/screenshots/sync/common） |
| Profile 插件 | `profiles/` | ProfileBase 基类 + 各 Profile handler（自动发现） |
| 业务域后端 | `workspaces/` | screen/doc/lab 三个业务域的专用后端 |
| UI 层 | `ui/` | NiceGUI 页面（layout/state/home/browser/tools/workspaces） |

## 文件结构

```
cyber_reel/
├── main.py                     # 入口；-testing-env 开关；-reload 控制 auto-reload
├── config_manager.py           # Profile 配置管理，读写 profiles_config.json
├── profiles_config.json        # 各 Profile 的 root/from/to/naming_rules/table_schema/screenshot_config
├── data.db                     # SQLite 数据库
├── core/                       # 纯后端，与 UI 完全解耦
│   ├── db.py                   # Database 类（SQLite 封装，thread-local 连接）
│   ├── files.py                # scan_videos / rename_files / rollback_records
│   ├── screenshots.py          # PyAV 截帧（resolve_time_points/extract_frame/capture_one_video）
│   ├── sync.py                 # diff_db / sync_db / build_db
│   └── common/                 # 常用选项后端（home/browser/tools 各一）
│       ├── dashboard.py        # get_dashboard_data（首页统计）
│       ├── browser.py          # filter_records / format_cell（浏览器过滤/格式化）
│       └── tools.py            # list_scripts / run_script（工具页脚本）
├── profiles/                   # Profile 插件（Registry 自动发现）
│   ├── __init__.py             # ProfileBase 基类 + ProfileRegistry
│   ├── movie/                  # 电影（dict 映射 normalize）
│   ├── tv/                     # 电视剧（dict 映射 normalize）
│   ├── realshot/               # 实拍（dict 映射 normalize）
│   └── homework/               # 作业（regex normalize + build_db 提取 series）
│       ├── handler.py          # XxxHandler(ProfileBase)，重写 normalize()/build_db()
│       ├── config.py           # PROFILE_KEY/NAME/VIDEO_EXTENSIONS/DEFAULT_ROOT
│       └── rules.py            # 命名规则（预留接口）
├── workspaces/                 # 业务域专用后端（screen/doc/lab）
│   ├── __init__.py             # WORKSPACES 定义 + workspace_of/workspace_menu
│   ├── _shared.py              # save_config（配置校验+保存，screen/lab 复用）
│   ├── screen/                 # 影视：config.py + sync.py + guide.md
│   ├── doc/                    # 纪实：仅 __init__.py（暂无专用选项）+ guide.md
│   └── lab/                    # 练习：config.py + guide.md
├── ui/
│   ├── layout.py               # 主布局：左抽屉（4 段）+ 右内容区
│   ├── state.py                # 全局状态 + switch_page/switch_workspace/render_workspace_menu
│   ├── home.py                 # 首页仪表盘
│   ├── browser_page.py         # 媒体浏览器（懒加载封面 + 截图弹窗）
│   ├── tools_page.py           # 工具页（脚本列表/源码/参数/运行结果）
│   └── workspaces/             # 业务域专用前端（screen/doc/lab）
│       ├── _shared.py          # build_config（配置页共享前端）
│       ├── screen/             # config_page.py + sync_page.py
│       ├── lab/                # config_page.py
│       └── doc/                # 空（暂无页面）
├── tools/                      # 工具页可运行脚本（scan_root/cipher/db_diff）
├── static/css/cyberpunk.css
└── .vscode/launch.json         # 两个启动配置（调试 / 运行·自动重启）
```

## 业务域（Workspace）划分

| Key | 中文 | 关联 Profile | 专用菜单 |
|---|---|---|---|
| screen | 影视 | movie, tv | config, sync |
| doc | 纪实 | realshot | （无） |
| lab | 练习 | homework | config |

- 左侧抽屉「CURRENT PROFILE」下的 radio 即按此划分切换业务域。
- `workspace_of(profile)` 由 `workspaces/__init__.py` 的 `_PROFILE_TO_WORKSPACE` 反查。
- 切换业务域 → `state.switch_workspace()` → 设默认 profile + 重建专用菜单 + 回首页。
- 每个业务域目录含 `guide.md` 说明该域职责与文件。

## 数据表

| 表名 | 用途 |
|---|---|
| `media_{profile}` | 各 Profile 独立媒体表（movie/tv/realshot/homework） |
| `screenshots` | 截图 BLOB，关联 mv_path + profile + time_point |
| `rename_history` | 文件重命名历史，支持批次/日期范围回滚 |

基础列 (id/title/mv_path/cover/crid/added_time) 始终存在，扩展列由各 Profile 的 `table_schema` 配置定义。

## 路径三要素

| 路径 | 语义 |
|---|---|
| `root` | 已整理视频目录，DB 同步 + 浏览器展示均扫描此目录 |
| `from` | 原始新视频目录，rename 的源 |
| `to` | 更名后目标目录，rename 的目标，rollback 的源 |

排除逻辑：from/to 若在 root 下，同步/浏览器自动排除对应子目录（`core/common/browser.py::get_exclude_dirs`）。

## 启动方式（.vscode/launch.json）

| 配置名 | 类型 | 说明 |
|---|---|---|
| CyberReel (调试) | debugpy | `reload=False`，可断点调试，带 `-testing-env` |
| CyberReel (运行·自动重启) | node-terminal | 直接跑 `python main.py -testing-env -reload`，`reload=True`，改代码保存后自动重启 |

- `-testing-env`：让 `ui/state.py` 的 `[区域名]` 标签变白可见，便于定位调试。
- `-reload`：`main.py` 里 `reload="-reload" in sys.argv` 门控。CLI 参数在 Windows multiprocessing spawn 子进程中仍保留，故无需 env 兜底。
- NiceGUI reload 用 uvicorn + spawn；子进程 `ui.run()` 在非 MainProcess 处提前 return。

## 关键设计决策

### 分层解耦
- UI 层禁止直接操作 SQLite / 文件系统；全部经 `core/` 纯函数或 `Database` 方法。
- `core/common/*` 是「常用选项」（首页/浏览器/工具）的纯后端，无 UI 依赖。
- `workspaces/` 是「专用选项」后端；`ui/workspaces/` 是其前端；二者镜像分层。

### 路径比较策略
- **禁止** `Path.resolve()` — Windows 上访问文件系统，UNC 路径/断网时失败。
- **使用** `os.path.normpath()` + `.lower()` 纯字符串比较，不依赖 IO。

### 命名规则架构
- Movie/TV/Realshot：`naming_rules = {"key": "value"}` → `str.replace`（`ProfileBase.normalize` 默认实现）。
- Homework：`naming_rules = {"pattern": "...", "replacement": "..."}` → `re.sub`（`HomeworkHandler.normalize` 重写）。
- 仅重命名名字实际变化的文件 `p.name != new_name`。

### 截图策略
- 指定时间点 `moments` 非空时按指定点截取，忽略 `count`。
- 时长已知：均分 `duration/(count+1)`；未知：fallback 几何级数 `[5,30,120,600,1800]`。
- 质量检查（<800KB 重试），重试帧仅在更大时替换。
- 列表页不渲染缩略图；`📷 N` 按钮点击后才加载 BLOB 弹窗；`🔍` 二次放大。

### 重命名策略（两阶段 UUID）
1. 全部 → `UUID.扩展名`（零冲突）；2. → 规范名（可选移动至 to）。
- 同名保护追加 `_1/_2`；操作记录到 `rename_history`。

### NiceGUI 注意事项
- HTML `<dialog>` + `onclick` 不可靠，用 `ui.dialog()` 组件。
- `sqlite3.Row` 只支持 `[]` 和 `.keys()`，无 `.get()`。
- 弹窗宽度用 `_style["min-width"/"max-width"]` 而非 Tailwind 类。
- Quasar 内部样式需 `<style>` + `!important` 覆盖。
- HTML5 原生日期选择器：`ui.input().props("type=date")`。
- 阻塞 IO（tkinter 目录选择、文件扫描、PyAV 截帧）用 `run.io_bound` / `asyncio.to_thread`，不阻塞事件循环。

### 停止按钮
- `state.request_cancel()` 设 `threading.Event`；截图/同步等运行函数通过 `cancel_requested()` 轮询中断。

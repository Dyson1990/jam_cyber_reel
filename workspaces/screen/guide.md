# screen — 影视业务域

## 定位
影视业务域，涵盖电影（movie）和电视剧（tv）两个 Profile。
功能最全的 workspace：扫描 + 标准化 + 截图。

## 关联 Profile
- movie — 电影（默认 profile）
- tv — 电视剧

## 后端文件（workspaces/screen/）
- `__init__.py` — 业务标识
- `config.py` — 各 Profile 默认配置（含 naming_mode/ai_api_key/ai_prompt 等 AI 命名骨架参数）
- `sync.py` — 同步后端入口，转发 `core/sync.py` 的 `diff_db`/`sync_db`/`build_db`

## 前端文件（ui/workspaces/screen/）
- `_shared.py` — 共享工具：日志区、顶部电影/电视剧单选、运行状态栏
- `scan_page.py` — 扫描（root + crid 正则 + 对比差异/数据库同步）
- `normalize_page.py` — 标准化（from/to + 映射命名/AI 命名两页 + 重命名/回滚）
- `screenshot_page.py` — 截图（root + count/moments + 截取截图）

## 专用菜单
扫描（scan）、标准化（normalize）、截图（screenshot）

## 共享参数
三模块顶端均有「电影 / 电视剧」单选，切换即写 `config_mgr.current_profile`（跨模块共享）。
各参数输入即保存（on_change → `update_profile_config`），电影/电视剧参数按 profile 分开存储。

## Profile 插件
movie / tv 无自定义逻辑，`ProfileRegistry.discover()` 回退默认 `ProfileBase`
（dict 映射改名，行为由 config 的 `naming_rules` 决定）。

如需影视特有逻辑，在 `workspaces/screen/` 新建 `profile.py`，定义继承 `ProfileBase`
的 handler 并声明 `profile_name`（`"movie"` / `"tv"`）即可，注册代码无需改动。

## 依赖的 core 模块
- `core/sync.py` — 数据库同步
- `core/files.py` — 文件扫描 / 重命名 / 回滚
- `core/screenshots.py` — 截图采集（PyAV）

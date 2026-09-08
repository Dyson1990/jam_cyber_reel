# screen — 影视业务域

## 定位
影视业务域，涵盖电影（movie）和电视剧（tv）两个 Profile。
功能最全的 workspace：配置 + 同步。

## 关联 Profile
- movie — 电影（默认 profile）
- tv — 电视剧

## 后端文件（workspaces/screen/）
- `__init__.py` — 业务标识
- `config.py` — 配置后端入口，复用 `workspaces/_shared.py` 的 `save_config`
- `sync.py` — 同步后端入口，转发 `core/sync.py` 的 `diff_db`/`sync_db`/`build_db`

## 前端文件（ui/workspaces/screen/）
- `config_page.py` — 配置页，复用 `ui/workspaces/_shared.py` 的 `build_config`
- `sync_page.py` — 同步页（DB 同步 + 截图采集 + 文件名更新 + 回滚）

## 专用菜单
配置（config）、同步（sync）

## Profile 插件
movie / tv 无自定义逻辑，`ProfileRegistry.discover()` 回退默认 `ProfileBase`
（dict 映射改名，行为由 config 的 `naming_rules` 决定）。

如需影视特有逻辑，在 `workspaces/screen/` 新建 `profile.py`，定义继承 `ProfileBase`
的 handler 并声明 `profile_name`（`"movie"` / `"tv"`）即可，注册代码无需改动。

## 依赖的 core 模块
- `core/sync.py` — 数据库同步
- `core/files.py` — 文件扫描 / 重命名 / 回滚
- `core/screenshots.py` — 截图采集（PyAV）

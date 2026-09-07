# doc — 纪实业务域

## 定位
纪实业务域，目前仅 realshot（实拍）一个 Profile。
暂无专用选项菜单（`WORKSPACES["doc"]["menu"]` 为空）。

## 关联 Profile
- realshot — 实拍（默认 profile）

## 后端文件（workspaces/doc/）
- `__init__.py` — 业务标识（暂无其它逻辑）

## 前端文件（ui/workspaces/doc/）
- `__init__.py` — 前端标识（暂无页面）

## 新增专用功能的方法
1. 在 `workspaces/__init__.py` 的 `WORKSPACES["doc"]["menu"]` 中加入页面 key（如 `"sync"`）
2. 在 `workspaces/doc/` 实现对应后端逻辑
3. 在 `ui/workspaces/doc/` 实现对应前端页面
4. 在 `ui/state.py` 的 `switch_page()` 中接入新页面构建函数

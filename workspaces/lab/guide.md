# lab — 练习业务域

## 定位
练习业务域，对应 homework（作业 / 学习视频）Profile。
命名规则使用 regex，区别于 movie/tv 的 dict 字符串替换。

## 关联 Profile
- homework — 作业（默认 profile）

## 后端文件（workspaces/lab/）
- `__init__.py` — 业务标识
- `config.py` — 配置后端入口，复用 `workspaces/_shared.py` 的 `save_config`

## 前端文件（ui/workspaces/lab/）
- `config_page.py` — 配置页，复用 `ui/workspaces/_shared.py` 的 `build_config`

## 专用菜单
配置（config）

## 特殊逻辑
`profiles/homework/handler.py` 的 `HomeworkHandler` 重写了：
- `normalize()` — 用 `re.sub(pattern, replacement, stem)` 规范化文件名（naming_rules 存 pattern/replacement）
- `build_db()` — 额外从文件名提取课程编号作为 `series` 列

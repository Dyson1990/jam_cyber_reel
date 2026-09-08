# lab — 练习业务域

## 定位
练习业务域，对应 homework（作业 / 学习视频）Profile。
命名规则使用 regex，区别于 movie/tv 的 dict 字符串替换。

## 关联 Profile
- homework — 作业（默认 profile）

## 后端文件（workspaces/lab/）
- `__init__.py` — 业务标识
- `config.py` — 配置后端入口，复用 `workspaces/_shared.py` 的 `save_config`
- `profile.py` — homework 的 Profile 插件（HomeworkHandler）

## 前端文件（ui/workspaces/lab/）
- `config_page.py` — 配置页，复用 `ui/workspaces/_shared.py` 的 `build_config`

## 专用菜单
配置（config）

## Profile 插件（HomeworkHandler）
`workspaces/lab/profile.py` 的 `HomeworkHandler` 继承 `ProfileBase` 并重写了：
- `normalize()` — 用 `re.sub(pattern, replacement, stem)` 规范化文件名（naming_rules 存 pattern/replacement）
- `build_db()` — 额外从文件名提取课程编号作为 `series` 列

## 插件扩展机制
Profile 业务逻辑以「插件」形式挂在各 workspace 下，由 `workspaces/_shared.py` 的
`ProfileRegistry.discover()` 自动加载：

1. **发现规则**：对每个 profile，按其 `workspace_of()` 定位 workspace，尝试
   `import workspaces.<ws>.profile` 并匹配声明了同名 `profile_name` 的 `ProfileBase` 子类。
2. **回退**：未找到自定义 handler 时，自动回退默认 `ProfileBase`（dict 映射改名），
   无需为空壳 profile 建文件。
3. **扩展方法**（新增/定制某 profile 的逻辑）：
   - 在对应 workspace 下新建 `profile.py`
   - 定义 `class XxxHandler(ProfileBase)`，声明 `profile_name = "<profile key>"`
   - 按需 override `normalize()` / `build_db()` / `scan()` 等方法
   - 无需改任何注册代码，`discover()` 会自动发现

本域即通过上述方式，把 homework 独有的 regex 规范化 + 课程编号提取注入到 `HomeworkHandler`。

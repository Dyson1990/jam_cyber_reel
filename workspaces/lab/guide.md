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
- `dts/` — DTS 专利音轨检测（PyAV 遍历音频流，按编码名 dca/dts 判定）
- `subtitle/` — 字幕提取（PyAV 解码文本字幕流转 SRT）

## 前端文件（ui/workspaces/lab/）
- `config_page.py` — 配置页，复用 `ui/workspaces/_shared.py` 的 `build_config`
- `dts.py` — DTS 检测页
- `subtitle.py` — 字幕提取页

## 专用菜单
配置 → DTS 检测 → 字幕提取

## 功能研究约定
lab 下一种功能的研究，其代码全部放在一个文件夹内（后端 `workspaces/lab/<功能>/`，
前端 `ui/workspaces/lab/<功能>.py`），对应网站菜单栏「概览」按钮下方的一个新按钮：
1. 后端新建 `workspaces/lab/<功能>/__init__.py` 导出纯函数（不依赖 UI / DB）
2. 前端新建 `ui/workspaces/lab/<功能>.py` 定义 `build_<功能>(config_mgr, db, registry)`
3. 在 `ui/workspaces/lab/__init__.py` 的 `PAGES` 登记 page key → (图标, 标签, "模块:构建函数")
4. 在 `workspaces/__init__.py` 的 `WORKSPACES["lab"]["menu"]` 追加该 page key

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

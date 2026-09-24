"""
UI 共享状态模块 - 保存全局引用，打破循环导入。

文件作用：
    将 layout.py 中的全局变量和页面切换函数提取到此模块，
    使 config_page.py 等页面模块可以导入而不会形成循环依赖。

设计理由：
    layout.py 导入各页面模块，若页面模块反向导入 layout.py
    则形成循环导入。提取共享状态到独立的 state 模块解决此问题。

主要变量：
    content_area   - 右侧内容区容器
    profile_label  - 左侧菜单中 Current Profile 显示
    root_label     - 左侧菜单中 Root 显示
    status_text    - 左侧菜单底部状态栏
    config_mgr     - 全局 ConfigManager 实例
    db_instance    - 全局 Database 实例
    registry       - 全局 ProfileRegistry 实例

主要函数：
    switch_page(page)        - 切换右侧内容区页面
    update_drawer_info()    - 更新左侧菜单信息
"""

import importlib
import threading

from nicegui import ui

from workspaces import WORKSPACES, workspace_of, workspace_menu, workspace_default_profile

# 取消标记：停止按钮设置此事件，各运行函数检查后中断
_cancel_event = threading.Event()

# 页面注册表：page key → (图标, 中文标签, "module:builder")。
# 框架页面在此登记；各 workspace 的专用页面在 ui/workspaces/<ws>/__init__.py 的 PAGES 登记，
# 由 _register_workspace_pages() 首次渲染时合并，框架代码不感知具体业务页。
PAGES = {
    "home": ("◇", "首页", "ui.home:build_home"),
    "browser": ("▤", "媒体浏览器", "ui.browser_page:build_browser"),
    "tools": ("◆", "工具", "ui.tools_page:build_tools"),
    "overview": ("◈", "概览", "ui.home:build_overview"),
    "config": ("⚙", "配置", "ui.workspaces._shared:build_config"),
}

_pages_registered = False


def _register_workspace_pages():
    """首次调用时合并各 workspace 的专用页面与扩展。

    按 WORKSPACES 键动态导入 ui.workspaces.<ws>，不硬编码业务名；
    每个 workspace 可声明 PAGES 字典与可选 register() 钩子（注册概览扩展等）。
    """
    global _pages_registered
    if _pages_registered:
        return
    _pages_registered = True
    for ws in WORKSPACES:
        try:
            mod = importlib.import_module(f"ui.workspaces.{ws}")
        except ModuleNotFoundError:
            continue
        for key, entry in getattr(mod, "PAGES", {}).items():
            PAGES[key] = entry
        register = getattr(mod, "register", None)
        if callable(register):
            register()


def _resolve_builder(spec: str):
    """把 "module:attr" 解析为页面构建函数（延迟导入，打破循环引用）。"""
    mod_name, attr = spec.split(":")
    return getattr(importlib.import_module(mod_name), attr)


def cancel_requested() -> bool:
    """检查是否请求取消（不清除标记）。"""
    return _cancel_event.is_set()


def request_cancel():
    """设置取消标记（停止按钮回调）。"""
    _cancel_event.set()


def clear_cancel():
    """清除取消标记（运行开始时调用）。"""
    _cancel_event.clear()


# 标签字体颜色：默认透明（与背景同色，仅留于 DOM）；以 -testing-env 启动时改为白色可见
TESTING_ENV = False


def tag(name: str):
    """渲染区域名标签 [name]；默认透明，-testing-env 时白色可见。"""
    color = "text-white" if TESTING_ENV else "text-transparent"
    ui.label(f"[{name}]").classes(f"text-xs {color} font-mono")

# 全局 UI 引用
content_area: ui.column = None
profile_label: ui.label = None
root_label: ui.label = None
status_text: ui.label = None
status_progress: ui.linear_progress = None
workspace_radio: ui.radio = None

# 全局核心实例引用
config_mgr = None
db_instance = None
registry = None

# 第③段专用选项菜单容器（layout.py 中赋值，随 workspace 切换重建）
workspace_menu_container: ui.column = None

# ===== 会话级业务状态（单一数据源）=====
# 页面销毁重建（switch_page 的 clear+rebuild）只丢视图，不丢这些数据；
# 后台任务只写这里，视图从这里渲染。这就是「状态与视图解耦」的落点。
log_lines: dict[str, list[tuple[str, str]]] = {}  # screen 各页日志：page -> [(消息, 颜色)]，互不干扰
task: dict = {"key": "", "name": "", "status": "idle"}  # 当前任务：key=按钮标识, status∈idle/running/ready/error
page: dict = {}                                # 各页瞬态数据，如 page["normalize"]["ai"]={"result":{...},"selected":{...}}


def switch_page(page: str):
    """切换右侧内容区页面。"""
    _register_workspace_pages()
    _, _, spec = PAGES[page]
    builder = _resolve_builder(spec)

    content_area.clear()
    with content_area:
        builder(config_mgr, db_instance, registry)

    status_text.set_text("就绪") if status_text else None
    if status_progress:
        status_progress.set_value(0)


def render_workspace_menu():
    """重建第③段专用选项菜单（按当前 workspace 的专用项）。"""
    if workspace_menu_container is None:
        return
    _register_workspace_pages()
    workspace_menu_container.clear()
    key = workspace_of(config_mgr.current_profile)
    with workspace_menu_container:
        # 概览固定为每个工作区的首个入口
        for page in ["overview", *workspace_menu(key)]:
            icon, label = PAGES[page][:2]
            btn = ui.button(
                f"{icon}  {label}",
                on_click=lambda _, p=page: switch_page(p),
            )
            btn.classes(
                "w-full text-left bg-slate-950 hover:bg-cyan-900 text-cyan-300 "
                "border border-cyan-800 rounded font-mono text-sm py-2 "
                "transition-colors duration-200"
            )
            btn.style("justify-content: flex-start;")


def switch_workspace(key: str):
    """切换业务域：设 current_profile 为默认 profile，刷新菜单与首页。"""
    config_mgr.current_profile = workspace_default_profile(key)
    render_workspace_menu()
    update_drawer_info()
    switch_page("overview")


def update_drawer_info():
    """更新左侧抽屉中 Root 和 Current Profile 的显示。"""
    if config_mgr and profile_label:
        profile_label.set_text(config_mgr.current_profile)
    if config_mgr and root_label:
        root = config_mgr.get_profile_root() or "/"
        root_label.set_text(root)
    if config_mgr and workspace_radio:
        workspace_radio.set_value(workspace_of(config_mgr.current_profile))

    status_text.set_text("就绪") if status_text else None
    if status_progress:
        status_progress.set_value(0)

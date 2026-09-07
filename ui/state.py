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

import threading

from nicegui import ui

from workspaces import workspace_of, workspace_menu, workspace_default_profile

# 取消标记：停止按钮设置此事件，各运行函数检查后中断
_cancel_event = threading.Event()

# 菜单项定义：page key → (图标, 中文标签)
MENU_ITEMS = {
    "home": ("◇", "首页"),
    "browser": ("▤", "媒体浏览器"),
    "tools": ("◆", "工具"),
    "config": ("⚙", "配置"),
    "sync": ("↻", "同步"),
}


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

# 页面模块延迟到 switch_page 内导入以打破循环引用

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


def switch_page(page: str):
    """切换右侧内容区页面。

    实现机制：
        content_area.clear() 清除当前页面元素，
        然后用 with content_area: 块重建目标页面。

    Args:
        page: 目标页面名称（home/config/sync/browser/tools）
    """
    from ui.home import build_home
    from ui.browser_page import build_browser
    from ui.tools_page import build_tools
    from ui.workspaces._shared import build_config
    from ui.workspaces.screen.sync_page import build_sync

    content_area.clear()
    with content_area:
        if page == "home":
            build_home(config_mgr, db_instance)
        elif page == "config":
            build_config(config_mgr, registry)
        elif page == "sync":
            build_sync(config_mgr, db_instance, registry)
        elif page == "browser":
            build_browser(config_mgr, db_instance)
        elif page == "tools":
            build_tools(config_mgr, db_instance)

    status_text.set_text("就绪") if status_text else None
    if status_progress:
        status_progress.set_value(0)


def render_workspace_menu():
    """重建第③段专用选项菜单（按当前 workspace 的专用项）。"""
    if workspace_menu_container is None:
        return
    workspace_menu_container.clear()
    key = workspace_of(config_mgr.current_profile)
    with workspace_menu_container:
        for page in workspace_menu(key):
            icon, label = MENU_ITEMS[page]
            btn = ui.button(
                f"{icon}  {label}",
                on_click=lambda _, p=page: switch_page(p),
            )
            btn.classes(
                "w-full text-left bg-gray-900 hover:bg-cyan-900 text-cyan-300 "
                "border border-cyan-800 rounded font-mono text-sm py-2 "
                "transition-colors duration-200"
            )
            btn.style("justify-content: flex-start;")


def switch_workspace(key: str):
    """切换业务域：设 current_profile 为默认 profile，刷新菜单与首页。"""
    config_mgr.current_profile = workspace_default_profile(key)
    render_workspace_menu()
    update_drawer_info()
    switch_page("home")


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

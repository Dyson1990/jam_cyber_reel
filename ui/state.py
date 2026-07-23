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

# 取消标记：停止按钮设置此事件，各运行函数检查后中断
_cancel_event = threading.Event()


def cancel_requested() -> bool:
    """检查是否请求取消（不清除标记）。"""
    return _cancel_event.is_set()


def request_cancel():
    """设置取消标记（停止按钮回调）。"""
    _cancel_event.set()


def clear_cancel():
    """清除取消标记（运行开始时调用）。"""
    _cancel_event.clear()

# 页面模块延迟到 switch_page 内导入以打破循环引用

# 全局 UI 引用
content_area: ui.column = None
profile_label: ui.label = None
root_label: ui.label = None
status_text: ui.label = None
status_progress: ui.linear_progress = None

# 全局核心实例引用
config_mgr = None
db_instance = None
registry = None


def switch_page(page: str):
    """切换右侧内容区页面。

    实现机制：
        content_area.clear() 清除当前页面元素，
        然后用 with content_area: 块重建目标页面。

    Args:
        page: 目标页面名称（home/config/sync/browser/tools）
    """
    from ui.home import build_home
    from ui.config_page import build_config
    from ui.sync_page import build_sync
    from ui.browser_page import build_browser
    from ui.tools_page import build_tools

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


def update_drawer_info():
    """更新左侧抽屉中 Root 和 Current Profile 的显示。"""
    if config_mgr and profile_label:
        profile_label.set_text(config_mgr.current_profile)
    if config_mgr and root_label:
        root = config_mgr.get_profile_root() or "/"
        root_label.set_text(root)

    status_text.set_text("就绪") if status_text else None
    if status_progress:
        status_progress.set_value(0)

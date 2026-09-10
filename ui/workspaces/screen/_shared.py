"""
screen 三模块（扫描 / 标准化 / 截图）共享 UI 工具。

文件作用：
    1. 共享日志区（右侧 absolute 面板 + 彩色日志 + 定时滚到底）
    2. 顶部电影/电视剧单选（跨模块共享 current_profile）
    3. 运行状态栏辅助（_set_running / _set_ready）

三个页面各调用 build_log_panel() 绑定到同一个模块级 _log_container；
页面切换时 content_area.clear() 会销毁旧面板，新页面重建后重新绑定。
"""

from nicegui import ui

from workspaces import WORKSPACES, workspace_of
from ui.state import update_drawer_info, switch_page, clear_cancel, tag


# 模块级共享日志容器引用（build_log_panel 中赋值，页面切换时自动重建）
_log_container: ui.column = None
_log_scroll_nicegui_id: int = 0


def log(msg: str, color: str = "gray"):
    """向右侧共享日志区追加一条带颜色的日志。"""
    if _log_container is None:
        return
    color_cls = {
        "cyan": "text-cyan-400",
        "gray": "text-slate-400",
        "green": "text-blue-400",
        "red": "text-red-400",
        "yellow": "text-orange-400",
    }.get(color, "text-slate-400")
    with _log_container:
        ui.label(msg).classes(f"font-mono text-xs {color_cls}")


def clear_log():
    """清空共享日志区，重置取消标记。"""
    clear_cancel()
    if _log_container is not None:
        _log_container.clear()


def set_running(label: str):
    """设置状态栏为 '运行：<功能名>'。"""
    from ui.state import status_text
    if status_text:
        status_text.set_text(f"运行：{label}")


def set_ready():
    """恢复状态栏为就绪。"""
    from ui.state import status_text, status_progress
    if status_text:
        status_text.set_text("就绪")
    if status_progress:
        status_progress.set_value(0)


def build_profile_radio(config_mgr, page: str):
    """顶部电影/电视剧单选（共享）。

    切换时写 current_profile + 刷新抽屉 + 重建当前页，
    使各输入框切到该 profile 的参数。因 current_profile 全局唯一，跨模块共享。
    """
    profile = config_mgr.current_profile
    ws_profiles = WORKSPACES[workspace_of(profile)]["profiles"]
    options = {
        p: config_mgr.get_profile_config(p).get("name", p) for p in ws_profiles
    }

    def on_change(e):
        config_mgr.current_profile = e.value
        update_drawer_info()
        switch_page(page)

    with ui.row().classes("gap-3 items-center mb-4"):
        tag("profile-radio")
        ui.label("影视类型:").classes("text-sm font-mono text-slate-400")
        ui.radio(options, value=profile, on_change=on_change).props("inline").classes(
            "text-cyan-300"
        )


def build_log_panel():
    """渲染右侧共享日志面板（absolute 定位，与左侧卡片严格等高）。"""
    global _log_container, _log_scroll_nicegui_id

    with ui.card().classes(
        "bg-slate-950 border border-cyan-800 rounded-lg p-4"
    ).style(
        "position: absolute; top: 0; right: 0; bottom: 0; width: 38%; "
        "display: flex; flex-direction: column;"
    ):
        tag("log-panel")
        ui.label("◆ 运行日志").classes("text-lg font-mono text-cyan-400 mb-3 flex-none")
        scroll_area = ui.column().classes("overflow-y-auto w-full").style(
            "flex: 1 1 0%; min-height: 0;"
        )
        _log_container = scroll_area
        _log_scroll_nicegui_id = scroll_area.id

        def _scroll_log():
            ui.run_javascript(
                f'var e=getHtmlElement({_log_scroll_nicegui_id});'
                f'if(e)e.scrollTop=e.scrollHeight;',
                timeout=0,
            )
        ui.timer(0.3, _scroll_log)

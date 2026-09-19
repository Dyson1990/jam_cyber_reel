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


# 霓虹配色（16 进制）：内联 style 直接作用于整颗按钮，无需 Tailwind 动态编译。
# （曾用 Tailwind bg-*/text-*/border-*，动态加类会触发 Play CDN JIT 重编译，造成 1-2s 变色延迟）
_NEON = {
    "cyan":   ("#164e63", "#67e8f9", "#0891b2"),
    "blue":   ("#1e3a8a", "#93c5fd", "#2563eb"),
    "purple": ("#581c87", "#d8b4fe", "#9333ea"),
    "green":  ("#14532d", "#86efac", "#16a34a"),
    "orange": ("#7c2d12", "#fdba74", "#ea580c"),
    "red":    ("#7f1d1d", "#fca5a5", "#dc2626"),
    "amber":  ("#78350f", "#fcd34d", "#d97706"),
}

_active_btn = None
_active_btn_color = ""


def _btn_style(color: str) -> str:
    """按色名返回内联 CSS：bg=填充 / color=文字 / border=边框，整颗按钮一起变色。"""
    bg, text, border = _NEON[color]
    return f"background-color: {bg}; color: {text}; border: 1px solid {border};"


def run_button(label: str, color: str, on_click, pad: str = "px-6 py-2"):
    """创建业务按钮：点击即切运行色；回调内 set_ready()/set_error() 决定结束态。

    color=None 关闭 Quasar 默认 primary 底色（其 bg-primary 带 !important 会锁死填充色）。
    """
    btn = ui.button(label, color=None).classes(f"font-mono {pad}").style(_btn_style(color))

    async def _click():
        _mark_running(btn, color)
        await on_click()

    btn.on_click(_click)
    return btn


def _mark_running(btn, color: str):
    """切到运行色并记为当前活动按钮，供 set_ready/set_error 恢复。"""
    global _active_btn, _active_btn_color
    _active_btn, _active_btn_color = btn, color
    btn.style(replace=_btn_style("amber"))


def set_running(label: str):
    """设置状态栏为 '运行：<功能名>'（按钮色由 run_button 负责）。"""
    from ui.state import status_text
    if status_text:
        status_text.set_text(f"运行：{label}")


def _finish(text: str, color: str | None):
    """结束态统一处理：恢复/变色当前活动按钮 + 状态栏 + 进度归零。"""
    global _active_btn
    if _active_btn is not None:
        _active_btn.style(replace=_btn_style(color or _active_btn_color))
        _active_btn = None
    from ui.state import status_text, status_progress
    if status_text:
        status_text.set_text(text)
    if status_progress:
        status_progress.set_value(0)


def set_ready():
    """业务结束：按钮恢复原色，状态栏标「就绪」。"""
    _finish("就绪", None)


def set_error():
    """业务报错：按钮切霓虹红，状态栏标「出错」。"""
    _finish("出错", "red")


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


def mask_key(key: str) -> str:
    """脱敏显示 key：仅保留前 3 后 4 位，其余打码。"""
    if not key:
        return "未设置"
    if len(key) <= 7:
        return "*******"
    return f"{key[:3]}****{key[-4:]}"


def save_tmdb_key(config_mgr, profile, value, key_input):
    """录入 TMDB key：非空才覆盖保存，并刷新输入框为脱敏显示。"""
    if value:
        config_mgr.update_profile_config(profile, "tmdb_api_key", value)
        key_input.set_value(mask_key(value))


def save_tvdb_key(config_mgr, profile, value, key_input):
    """录入 TVDB key：非空才覆盖保存，并刷新输入框为脱敏显示。"""
    if value:
        config_mgr.update_profile_config(profile, "tvdb_api_key", value)
        key_input.set_value(mask_key(value))


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

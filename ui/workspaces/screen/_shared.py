"""
screen 各模块共享 UI 工具。

文件作用：
    1. 共享日志区（右侧 absolute 面板 + 彩色日志 + 定时滚到底）
    2. 顶部电影/电视剧单选（跨模块共享 current_profile）
    3. 业务按钮 + 运行状态栏（run_button / set_running / set_ready / set_error）

状态与视图解耦：日志「真身」是 state.log_lines，按钮色是 state.task 的投影。
页面切换的 clear+重建只销毁视图，数据在 ui.state 的 store 里，重建时重放/重绘。
"""

from datetime import datetime

from nicegui import ui

from core.logging_config import get_log_dir
from workspaces import WORKSPACES, workspace_of
import ui.state as state
from ui.state import update_drawer_info, switch_page, clear_cancel, tag


# 模块级共享日志容器引用（build_log_panel 中赋值，页面切换时自动重建）
# 日志的「真身」是 state.log_lines（按页分桶），_log_container 只是当前可见面板的视图句柄。
# _log_container_page 记录该面板所属页面，用于把后台任务的实时追加路由回它自己的面板，
# 而不是当前正被查看的页面（切页后仍在跑的任务，日志应写回发起页）。
_log_container: ui.column = None
_log_container_page: str = ""
_log_scroll_nicegui_id: int = 0


def _color_cls(color: str) -> str:
    return {
        "cyan": "text-cyan-400",
        "gray": "text-slate-400",
        "green": "text-blue-400",
        "red": "text-red-400",
        "yellow": "text-orange-400",
    }.get(color, "text-slate-400")


def make_page_logger(page: str):
    """返回绑定到指定页面的 (log, clear_log)。

    每个屏幕页用自己的 log/clear_log，日志落到 state.log_lines[page]，页与页互不干扰；
    切页只重建视图、不丢数据（buffer 在 store 里，build_log_panel 会重放）。
    log 通过闭包捕获 page，所以后台任务即使切页后仍在写，也会写回它所属页面的 buffer，
    而不是当前可见页面。"""
    def log(msg: str, color: str = "gray"):
        state.log_lines.setdefault(page, []).append((msg, color))
        _persist_log(page, msg)
        if _log_container is not None and not _log_container.is_deleted and _log_container_page == page:
            with _log_container:
                ui.label(msg).classes(f"font-mono text-xs {_color_cls(color)}")

    def clear_log():
        clear_cancel()
        state.log_lines.setdefault(page, []).clear()
        if _log_container is not None and not _log_container.is_deleted and _log_container_page == page:
            _log_container.clear()

    return log, clear_log


def _persist_log(page: str, msg: str) -> None:
    """业务日志落盘：UI 日志面板是瞬时的，按页分文件落盘供离线排查/回看。"""
    log_dir = get_log_dir()
    if not log_dir:
        return
    screen_dir = log_dir / "screen"
    screen_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(screen_dir / f"{page}.log", "a", encoding="utf-8") as f:
        f.write(f"{ts} | {msg}\n")


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

# 活动按钮注册表：(按钮, key, 基础色)。按钮是视图，颜色是状态 state.task 的投影。
# 重建页面时 run_button 重新登记；已删按钮在 _refresh_buttons 里被剔除，任务无需持按钮引用。
_btn_registry: list[tuple[ui.button, str, str]] = []


def _btn_style(color: str) -> str:
    """按色名返回内联 CSS：bg=填充 / color=文字 / border=边框，整颗按钮一起变色。"""
    bg, text, border = _NEON[color]
    return f"background-color: {bg}; color: {text}; border: 1px solid {border};"


def _color_for(key: str, base: str) -> str:
    """按钮当前应显颜色 = 基础色在任务态上的投影：运行→amber，出错→red。"""
    t = state.task
    if t["status"] == "running" and t["key"] == key:
        return "amber"
    if t["status"] == "error" and t["key"] == key:
        return "red"
    return base


def _refresh_buttons():
    """按 state.task 重刷所有存活按钮颜色，并剔除已销毁的按钮。"""
    global _btn_registry
    alive = []
    for btn, key, base in _btn_registry:
        if btn.is_deleted:
            continue
        alive.append((btn, key, base))
        btn.style(replace=_btn_style(_color_for(key, base)))
    _btn_registry = alive


def run_button(label: str, color: str, on_click, key: str | None = None, pad: str = "px-6 py-2"):
    """创建业务按钮。key 标识本次动作（缺省用 label），决定运行/出错时哪颗按钮变色。

    color=None 关闭 Quasar 默认 primary 底色（其 bg-primary 带 !important 会锁死填充色）。
    点击只写 state.task + 刷按钮，任务体内的 set_ready/set_error 再改状态；按钮从不被任务直接持有。
    """
    key = key or label
    btn = ui.button(label, color=None).classes(f"font-mono {pad}").style(_btn_style(_color_for(key, color)))

    async def _click():
        state.task.update(key=key, name=label, status="running")
        _refresh_buttons()
        try:
            await on_click()
        except Exception:
            # 任务异常且未自行 set_error 时兜底标红，不吞异常
            state.task.update(status="error")
            _refresh_buttons()
            raise

    btn.on_click(_click)
    # 登记前剔除已销毁按钮，避免页面反复销毁重建积累死引用
    _btn_registry[:] = [x for x in _btn_registry if not x[0].is_deleted]
    _btn_registry.append((btn, key, color))
    return btn


def set_running(label: str):
    """设置状态栏为 '运行：<功能名>'（按钮色由 run_button + state.task 负责）。"""
    state.task["name"] = label
    from ui.state import status_text
    if status_text:
        status_text.set_text(f"运行：{label}")


def _finish(text: str, color: str | None):
    """结束态统一处理：改 state.task 状态 → 刷按钮颜色 → 状态栏 + 进度归零。"""
    state.task["status"] = "error" if color == "red" else "ready"
    _refresh_buttons()
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


def build_log_panel(page: str):
    """渲染右侧日志面板（absolute 定位，与左侧卡片严格等高），仅重放本页日志。"""
    global _log_container, _log_container_page, _log_scroll_nicegui_id

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
        _log_container_page = page
        _log_scroll_nicegui_id = scroll_area.id
        # 从 store 重放本页历史日志：面板被销毁重建后依然完整（修复切页丢日志）
        for msg, color in state.log_lines.get(page, []):
            with _log_container:
                ui.label(msg).classes(f"font-mono text-xs {_color_cls(color)}")

        def _scroll_log():
            ui.run_javascript(
                f'var e=getHtmlElement({_log_scroll_nicegui_id});'
                f'if(e)e.scrollTop=e.scrollHeight;',
                timeout=0,
            )
        ui.timer(0.3, _scroll_log)

"""
主布局模块 - 定义 CyberReel 的整体页面结构。

菜单栏 4 段：
    ① CURRENT PROFILE（当前 Profile + Root）
    ② 常用选项（首页 / 媒体浏览器 / 工具）
    ③ 专用选项（随业务域 radio 变化）
    ④ 状态栏（STATUS + 停止按钮）
"""

from nicegui import run, ui

import ui.state as state
from workspaces import WORKSPACES, workspace_of


def create_layout(cfg_mgr, db, prof_registry):
    """创建主布局：左侧抽屉 + 右侧内容区。"""
    state.config_mgr = cfg_mgr
    state.db_instance = db
    state.registry = prof_registry

    # 页面头部
    with ui.header(elevated=True).classes("bg-gray-900 text-cyan-400"):
        ui.label("◆ CYBERREEL").classes("text-2xl font-mono tracking-widest glow-text")

    # 左侧抽屉菜单
    with ui.left_drawer(fixed=False).classes("bg-gray-950 border-r border-cyan-800") as drawer:
        drawer.style("width: 240px;")
        with ui.column().classes("p-4 w-full gap-2"):
            # ① CURRENT PROFILE
            state.tag("drawer-profile")
            ui.label("CURRENT PROFILE").classes("text-xs text-gray-500 font-mono")
            state.workspace_radio = ui.radio(
                {key: ws["label"] for key, ws in WORKSPACES.items()},
                value=workspace_of(cfg_mgr.current_profile),
                on_change=lambda e: state.switch_workspace(e.value),
            ).props("inline").classes("mb-2 text-cyan-300")
            state.profile_label = ui.label("—").classes("text-magenta-400 text-sm font-mono")
            with ui.row().classes("items-center gap-2 mt-2 w-full"):
                ui.label("ROOT").classes("text-xs text-gray-500 font-mono")
                _root_edit_button(cfg_mgr)
            state.root_label = ui.label("/").classes("text-cyan-400 text-sm font-mono truncate w-full")

            ui.separator().classes("my-2 border-cyan-900")

            # ② 常用选项
            state.tag("drawer-common")
            ui.label("COMMON").classes("text-xs text-gray-600 font-mono")
            for icon, label, page in [
                ("◇", "首页", "home"),
                ("▤", "媒体浏览器", "browser"),
                ("◆", "工具", "tools"),
            ]:
                _menu_button(icon, label, page)

            ui.separator().classes("my-2 border-cyan-900")

            # ③ 专用选项（随业务域变化）
            state.tag("drawer-specialized")
            ui.label("SPECIALIZED").classes("text-xs text-gray-600 font-mono")
            state.workspace_menu_container = ui.column().classes("w-full gap-2")
            state.render_workspace_menu()

            ui.separator().classes("my-2 border-cyan-900")

            # ④ 状态栏
            with ui.card().classes("bg-gray-800 border border-cyan-900 rounded p-2 w-full"):
                state.tag("drawer-status")
                ui.label("STATUS").classes("text-xs text-gray-500 font-mono")
                state.status_text = ui.label("就绪").classes(
                    "text-xs text-cyan-300 font-mono mt-1"
                )
                state.status_progress = ui.linear_progress(0, show_value=False).classes("mt-2")
                state.status_progress.style("height:8px;")
                ui.button(
                    "■ 停止",
                    on_click=lambda: state.request_cancel(),
                ).classes(
                    "w-full mt-2 bg-red-900 hover:bg-red-700 text-red-300 font-mono "
                    "border border-red-600 rounded text-xs py-1"
                )

            ui.separator().classes("my-2 border-cyan-900")
            ui.label("v1.0.0").classes("text-xs text-gray-600 font-mono mt-auto")

    # 右侧内容区
    state.content_area = ui.column().classes("w-full p-6 bg-gray-900 min-h-screen")

    # 启动时默认显示首页
    state.switch_page("home")
    state.update_drawer_info()


def _menu_button(icon: str, label: str, page: str):
    """渲染一个左侧菜单按钮。"""
    btn = ui.button(f"{icon}  {label}", on_click=lambda _, p=page: state.switch_page(p))
    btn.classes(
        "w-full text-left bg-gray-900 hover:bg-cyan-900 text-cyan-300 "
        "border border-cyan-800 rounded font-mono text-sm py-2 "
        "transition-colors duration-200"
    )
    btn.style("justify-content: flex-start;")


def _root_edit_button(cfg_mgr):
    """ROOT 旁编辑按钮：原生目录选择器修改当前 Profile 的 root 路径。"""
    async def on_click():
        root = await run.io_bound(_ask_directory, cfg_mgr)
        if root:
            cfg_mgr.update_profile_config(cfg_mgr.current_profile, "root", root)
            state.update_drawer_info()

    btn = ui.button("🔧", on_click=on_click)
    btn.props("flat dense round")
    btn.classes("text-cyan-300 text-sm")
    return btn


def _ask_directory(cfg_mgr):
    """原生目录选择器（阻塞，运行于后台线程）。"""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askdirectory(
        title="选择 Root 目录",
        initialdir=cfg_mgr.get_profile_root() or None,
    )
    root.destroy()
    return path

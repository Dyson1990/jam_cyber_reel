"""
主布局模块 - 定义 CyberReel 的整体页面结构。

文件作用：
    构建左侧抽屉菜单 + 右侧内容区的主框架。
    管理页面切换逻辑（清除内容区 → 重建目标页）。

与其它模块的关系：
    - main.py 调用 create_layout() 初始化界面
    - 通过 ui/state.py 共享全局状态（避免循环导入）
    - 各页面模块通过 state.switch_page 触发页面切换

页面切换为何能覆盖内容区：
    NiceGUI 的 context manager 机制：进入 with content: 块后，
    所有 UI 元素创建均归属该容器。切换页面时先 content.clear()
    清除所有子元素，再重建新页面，实现"覆盖"效果而非叠加。
"""

from nicegui import ui

import ui.state as state


def create_layout(cfg_mgr, db, prof_registry):
    """创建主布局：左侧抽屉 + 右侧内容区。

    布局结构：
        ┌──────────────────────────────────────┐
        │  Header: CyberReel                    │
        ├──────────┬───────────────────────────┤
        │ 左侧抽屉  │  右侧内容区               │
        │ ─────── │  (content_area)           │
        │ Root     │                           │
        │ Profile  │  页面内容在此切换           │
        │ ─────── │                           │
        │ ● 首页   │                           │
        │ ● 配置   │                           │
        │ ● 同步  │                           │
        │ ● 浏览器 │                           │
        └──────────┴───────────────────────────┘

    Args:
        cfg_mgr: ConfigManager 实例
        db: Database 实例
        prof_registry: ProfileRegistry 实例
    """
    # 直接写入 state 模块的属性（不能只用 global，那只会写 layout 模块的命名空间）
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
            # Root 显示
            ui.label("ROOT").classes("text-xs text-gray-500 font-mono")
            state.root_label = ui.label("/").classes("text-cyan-400 text-sm font-mono truncate w-full")

            # Current Profile 显示
            ui.label("CURRENT PROFILE").classes("text-xs text-gray-500 font-mono mt-4")
            state.profile_label = ui.label("—").classes("text-magenta-400 text-sm font-mono")

            ui.separator().classes("my-2 border-cyan-900")

            # 菜单按钮
            for icon, label, page in [
                ("◇", "首页", "home"),
                ("⚙", "配置", "config"),
                ("↻", "同步", "sync"),
                ("▤", "媒体浏览器", "browser"),
                ("◆", "工具", "tools"),
            ]:
                btn = ui.button(f"{icon}  {label}", on_click=lambda _, p=page: state.switch_page(p))
                btn.classes("w-full text-left bg-gray-900 hover:bg-cyan-900 text-cyan-300 "
                            "border border-cyan-800 rounded font-mono text-sm py-2 "
                            "transition-colors duration-200")
                btn.style("justify-content: flex-start;")

            ui.separator().classes("my-2 border-cyan-900")

            # 状态栏
            with ui.card().classes("bg-gray-800 border border-cyan-900 rounded p-2 w-full"):
                ui.label("STATUS").classes("text-xs text-gray-500 font-mono")
                state.status_text = ui.label("就绪").classes(
                    "text-sm text-cyan-200 font-mono mt-1"
                )

            ui.separator().classes("my-2 border-cyan-900")

            # 底部版本信息
            ui.label("v1.0.0").classes("text-xs text-gray-600 font-mono mt-auto")

    # 右侧内容区
    state.content_area = ui.column().classes("w-full p-6 bg-gray-900 min-h-screen")

    # 启动时默认显示首页
    state.switch_page("home")
    state.update_drawer_info()

"""
首页模块 - 系统概览仪表盘。

文件作用：
    展示当前 Profile 状态、文件统计、数据库统计等信息。
    顶部提供业务域单选（影视 / 纪实 / 练习），切换后刷新专用选项菜单。

与其它模块的关系：
    - 被 ui/layout.py 的 switch_page("home") 调用
    - 数据聚合委托 core/common/dashboard.py

主要函数：
    build_home(config_mgr, db) - 构建首页 UI
"""

from nicegui import ui

from core.common.dashboard import get_dashboard_data
from ui.state import tag


def build_home(config_mgr, db):
    """构建首页仪表盘 UI。

    Args:
        config_mgr: ConfigManager 实例
        db: Database 实例
    """
    data = get_dashboard_data(config_mgr, db)
    profile = data["profile"]

    tag("home")
    ui.label("◆ DASHBOARD").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")

    # 统计卡片行 —— 3 列网格
    with ui.row().classes("gap-4 w-full mb-6"):
        with ui.card().classes("bg-gray-950 border border-cyan-800 rounded-lg p-4 flex-1"):
            tag("current-profile")
            ui.label("CURRENT PROFILE").classes("text-xs text-gray-500 font-mono")
            ui.label(profile).classes("text-2xl font-mono text-magenta-400 mt-2")
            ui.label(data["display_name"]).classes("text-sm text-gray-400 mt-1")

        with ui.card().classes("bg-gray-950 border border-cyan-800 rounded-lg p-4 flex-1"):
            tag("files")
            ui.label("FILES").classes("text-xs text-gray-500 font-mono")
            ui.label(str(data["file_count"])).classes("text-3xl font-mono text-yellow-400 mt-2")

        with ui.card().classes("bg-gray-950 border border-cyan-800 rounded-lg p-4 flex-1"):
            tag("db-records")
            ui.label("DB RECORDS").classes("text-xs text-gray-500 font-mono")
            ui.label(str(data["total_records"])).classes("text-3xl font-mono text-cyan-400 mt-2")

    # 第二行：2 列
    with ui.row().classes("gap-4 w-full"):
        with ui.card().classes("bg-gray-950 border border-cyan-800 rounded-lg p-4 flex-1"):
            tag("last-sync")
            ui.label("LAST SYNC").classes("text-xs text-gray-500 font-mono")
            ui.label(data["last_sync"] or "尚未同步").classes(
                "text-lg font-mono text-cyan-300 mt-2"
            )

        with ui.card().classes("bg-gray-950 border border-cyan-800 rounded-lg p-4 flex-1"):
            tag("all-profiles")
            ui.label("ALL PROFILES").classes("text-xs text-gray-500 font-mono")
            for p in data["profiles"]:
                is_current = "◆" if p["key"] == profile else "◇"
                ui.label(
                    f"{is_current} {p['key']} — {p['name']} ({p['count']} files)"
                ).classes("text-sm font-mono text-gray-300 mt-1")

    # 重命名历史统计
    with ui.card().classes("bg-gray-950 border border-cyan-800 rounded-lg p-4 w-full mt-4"):
        tag("rename-history")
        ui.label("RENAME HISTORY").classes("text-xs text-gray-500 font-mono")
        ui.label(f"当前 Profile 共 {data['rename_count']} 条重命名记录").classes(
            "text-sm font-mono text-gray-400 mt-2"
        )

"""
首页模块 - 系统概览仪表盘。

文件作用：
    展示当前 Profile 状态、文件统计、数据库统计等信息。

与其它模块的关系：
    - 被 ui/layout.py 的 switch_page("home") 调用
    - 读取 ConfigManager 和 Database 获取统计数据

页面布局：
    ┌─────────────────────────────────────────┐
    │  ◆ DASHBOARD                            │
    ├──────────┬──────────┬───────────────────┤
    │ Profile  │ 文件数    │ 数据库记录数       │
    │ 名称卡片  │ 统计卡片   │ 统计卡片          │
    ├──────────┴──────────┴───────────────────┤
    │  最近同步时间                             │
    │  Profile 列表概览                         │
    └─────────────────────────────────────────┘

主要函数：
    build_home(config_mgr, db) - 构建首页 UI
"""

from nicegui import ui


def build_home(config_mgr, db):
    """构建首页仪表盘 UI。

    数据来源：
        - ConfigManager: 当前 Profile、Profile 列表
        - Database: 文件数量、数据库记录数、最近同步时间

    Args:
        config_mgr: ConfigManager 实例
        db: Database 实例

    调用时机：首次加载 layout 时，以及用户点击"首页"菜单时。
    """
    profile = config_mgr.current_profile
    cfg = config_mgr.get_profile_config()

    # 标题
    ui.label(f"◆ DASHBOARD").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")

    # 统计卡片行 —— 3 列网格
    with ui.row().classes("gap-4 w-full mb-6"):
        # 卡片1：当前 Profile
        with ui.card().classes("bg-gray-950 border border-cyan-800 rounded-lg p-4 flex-1"):
            ui.label("CURRENT PROFILE").classes("text-xs text-gray-500 font-mono")
            ui.label(profile).classes("text-2xl font-mono text-magenta-400 mt-2")
            ui.label(cfg.get("name", "")).classes("text-sm text-gray-400 mt-1")

        # 卡片2：文件数量
        with ui.card().classes("bg-gray-950 border border-cyan-800 rounded-lg p-4 flex-1"):
            ui.label("FILES").classes("text-xs text-gray-500 font-mono")
            file_count = db.get_media_count(profile)
            ui.label(str(file_count)).classes("text-3xl font-mono text-yellow-400 mt-2")

        # 卡片3：数据库记录数
        with ui.card().classes("bg-gray-950 border border-cyan-800 rounded-lg p-4 flex-1"):
            ui.label("DB RECORDS").classes("text-xs text-gray-500 font-mono")
            total = db.get_total_media_count()
            ui.label(str(total)).classes("text-3xl font-mono text-cyan-400 mt-2")

    # 第二行：2 列
    with ui.row().classes("gap-4 w-full"):
        # 最近同步
        with ui.card().classes("bg-gray-950 border border-cyan-800 rounded-lg p-4 flex-1"):
            ui.label("LAST SYNC").classes("text-xs text-gray-500 font-mono")
            import sqlite3
            row = db.fetchone(
                "SELECT timestamp FROM rename_history WHERE profile=? "
                "ORDER BY timestamp DESC LIMIT 1",
                (profile,),
            )
            last = row["timestamp"] if row else "尚未同步"
            ui.label(last).classes("text-lg font-mono text-cyan-300 mt-2")

        # Profile 概览
        with ui.card().classes("bg-gray-950 border border-cyan-800 rounded-lg p-4 flex-1"):
            ui.label("ALL PROFILES").classes("text-xs text-gray-500 font-mono")
            for pname in config_mgr.list_profiles():
                pcfg = config_mgr.get_profile_config(pname)
                is_current = "◆" if pname == profile else "◇"
                count = db.get_media_count(pname)
                ui.label(
                    f"{is_current} {pname} — {pcfg.get('name', '')} ({count} files)"
                ).classes("text-sm font-mono text-gray-300 mt-1")

    # 重命名历史统计
    with ui.card().classes("bg-gray-950 border border-cyan-800 rounded-lg p-4 w-full mt-4"):
        ui.label("RENAME HISTORY").classes("text-xs text-gray-500 font-mono")
        rename_count = db.get_rename_count_by_profile(profile)
        ui.label(f"当前 Profile 共 {rename_count} 条重命名记录").classes(
            "text-sm font-mono text-gray-400 mt-2"
        )

"""
首页模块 - 项目级首页 + 工作区概览页。

文件作用：
    build_home     — 项目级首页（运行日志 + 更新日志），与具体工作区无关
    build_overview — 工作区概览页（当前 Profile 的统计仪表盘）

与其它模块的关系：
    - 被 ui/state.py 的 switch_page("home"/"overview") 调用
    - 数据聚合委托 core/common/dashboard.py
"""

import json

from nicegui import ui

from core.common.dashboard import get_workspace_overview, get_changelog
from core.logging_config import read_recent_logs
from ui.state import tag, update_drawer_info
from workspaces._shared import parse_table_schema, parse_json_or


def build_home(config_mgr, db):
    """构建项目级首页：最新运行日志 + 更新日志。"""
    tag("home")
    ui.label("◆ HOME").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")

    # 最新运行日志：定时读取 logs/ 目录末尾，实时刷新
    with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-4 w-full mb-4"):
        tag("run-log")
        with ui.row().classes("w-full items-center justify-between mb-2"):
            ui.label("◆ 运行日志").classes("text-lg font-mono text-cyan-400")
            ui.label("每 3 秒自动刷新").classes("text-xs text-slate-600 font-mono")
        log_area = ui.column().classes("font-mono text-xs w-full overflow-y-auto").style(
            "max-height: 320px;"
        )

        def _refresh():
            log_area.clear()
            with log_area:
                lines = read_recent_logs(100)
                if not lines:
                    ui.label("暂无日志（启动后自动记录）").classes(
                        "text-slate-600 font-mono"
                    )
                    return
                for ln in lines:
                    ui.label(ln).classes(_line_color(ln))

        _refresh()
        ui.timer(3.0, _refresh)

    # 更新日志
    with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-4 w-full"):
        tag("changelog")
        ui.label("◆ 更新日志").classes("text-lg font-mono text-cyan-400 mb-2")
        for entry in get_changelog():
            ui.label(f"• {entry}").classes("text-sm font-mono text-slate-300 mt-1")


def _line_color(line: str) -> str:
    """按日志级别给运行日志行着色。"""
    parts = line.split(" | ")
    level = parts[1].strip() if len(parts) > 1 else ""
    if level in ("ERROR", "CRITICAL"):
        return "text-red-400"
    if level == "WARNING":
        return "text-orange-400"
    if level == "INFO":
        return "text-slate-300"
    return "text-slate-500"


def build_overview(config_mgr, db):
    """构建工作区概览页：当前 Profile 的统计仪表盘。"""
    data = get_workspace_overview(config_mgr, db)
    profile = data["profile"]

    tag("overview")
    ui.label("◆ 概览").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")

    # 统计卡片行 —— 3 列网格
    with ui.row().classes("gap-4 w-full mb-6"):
        with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-4 flex-1"):
            tag("current-profile")
            ui.label("CURRENT PROFILE").classes("text-xs text-slate-500 font-mono")
            ui.label(profile).classes("text-2xl font-mono text-magenta-400 mt-2")
            ui.label(data["display_name"]).classes("text-sm text-slate-400 mt-1")

        with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-4 flex-1"):
            tag("files")
            ui.label("FILES").classes("text-xs text-slate-500 font-mono")
            ui.label(str(data["file_count"])).classes("text-3xl font-mono text-orange-400 mt-2")

        with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-4 flex-1"):
            tag("db-records")
            ui.label("DB RECORDS").classes("text-xs text-slate-500 font-mono")
            ui.label(str(data["total_records"])).classes("text-3xl font-mono text-cyan-400 mt-2")

    # 第二行：2 列
    with ui.row().classes("gap-4 w-full"):
        with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-4 flex-1"):
            tag("last-sync")
            ui.label("LAST SYNC").classes("text-xs text-slate-500 font-mono")
            ui.label(data["last_sync"] or "尚未同步").classes(
                "text-lg font-mono text-cyan-300 mt-2"
            )

        with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-4 flex-1"):
            tag("workspace-profiles")
            ui.label("PROFILES").classes("text-xs text-slate-500 font-mono")
            for p in data["profiles"]:
                is_current = "◆" if p["key"] == profile else "◇"
                ui.label(
                    f"{is_current} {p['key']} — {p['name']} ({p['count']} files)"
                ).classes("text-sm font-mono text-slate-300 mt-1")

    # 重命名历史统计
    with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-4 w-full mt-4"):
        tag("rename-history")
        ui.label("RENAME HISTORY").classes("text-xs text-slate-500 font-mono")
        ui.label(f"当前 Profile 共 {data['rename_count']} 条重命名记录").classes(
            "text-sm font-mono text-slate-400 mt-2"
        )

    # 表结构 / 扩展配置编辑（原配置页的非功能参数，暂放概览）
    cfg = config_mgr.get_profile_config(profile)
    with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-4 w-full mt-4"):
        tag("schema-config")
        ui.label("表结构 / 扩展配置").classes("text-xs text-slate-500 font-mono")
        ui.label("表结构 (Table Schema):").classes("text-sm font-mono text-slate-400 mt-2 mb-1")
        schema_editor = ui.textarea(
            value=json.dumps(cfg.get("table_schema", []), ensure_ascii=False, indent=2)
        ).classes("w-full bg-slate-700 text-cyan-100 font-mono text-sm").style(
            "min-height: 100px;"
        )
        ui.label("扩展配置 (Extra Config):").classes("text-sm font-mono text-slate-400 mt-3 mb-1")
        extra_editor = ui.textarea(
            value=json.dumps(cfg.get("extra_config", {}), ensure_ascii=False, indent=2)
        ).classes("w-full bg-slate-700 text-cyan-100 font-mono text-sm").style(
            "min-height: 80px;"
        )
        status_label = ui.label("").classes("text-sm font-mono mt-2")
        ui.button(
            "◆ 保存",
            on_click=lambda: _save_schema(
                config_mgr, db, profile, schema_editor.value, extra_editor.value, status_label,
            ),
        ).classes(
            "bg-cyan-900 hover:bg-cyan-700 text-cyan-300 font-mono "
            "border border-cyan-600 rounded px-6 py-2 mt-3"
        )


def _save_schema(config_mgr, db, profile, schema_str, extra_str, status_label):
    """校验并保存当前 Profile 的表结构 / 扩展配置。"""
    try:
        schema = parse_table_schema(schema_str)
    except (json.JSONDecodeError, ValueError) as e:
        status_label.set_text(f"表结构 JSON 格式错误: {e}")
        status_label.classes("text-red-400 text-sm font-mono mt-2")
        return
    try:
        extra = parse_json_or(extra_str, {})
    except json.JSONDecodeError as e:
        status_label.set_text(f"扩展配置 JSON 格式错误: {e}")
        status_label.classes("text-red-400 text-sm font-mono mt-2")
        return

    config_mgr.update_profile_config(profile, "table_schema", schema)
    config_mgr.update_profile_config(profile, "extra_config", extra)
    # 补齐 media 表缺失的新增扩展列，避免后续 upsert 报「no such column」
    db.create_media_table(profile, schema)
    update_drawer_info()
    status_label.set_text("已保存 ✓")
    status_label.classes("text-blue-400 text-sm font-mono mt-2")

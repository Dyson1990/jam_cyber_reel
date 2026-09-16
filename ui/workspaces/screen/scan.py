"""
扫描模块（screen）— 数据库同步。

扫 from/to/root 三目录的顶层影视文件与压缩包（不递归子目录），
与 media 表对比、更新；每条记录写入来源（from/to/root）。

参数（输入即保存到 config_manager，跨模块共享）：
    from / to / root — 三个来源目录（通用，见 config.py）
"""

import asyncio

from pathlib import Path

from nicegui import ui

from core.logging_config import get_logger
from workspaces.screen.scan import diff_db, sync_db
from ui.state import tag, update_drawer_info, cancel_requested
from ui.workspaces.screen._shared import (
    log, clear_log, set_running, set_ready, set_error,
    run_button, build_profile_radio, build_log_panel,
)

logger = get_logger(__name__)

_SOURCE_LABEL = {"from": "from", "to": "to", "root": "root"}


def build_scan(config_mgr, db, registry):
    """构建扫描页 UI。"""
    profile = config_mgr.current_profile
    cfg = config_mgr.get_profile_config()

    tag("scan")
    ui.label("◆ 扫描").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")
    build_profile_radio(config_mgr, "scan")

    with ui.row().classes("w-full").style("position: relative;"):
        with ui.column().classes("flex-1 min-w-0").style("margin-right: calc(38% + 1rem);"):
            with ui.card().classes(
                "bg-slate-950 border border-cyan-800 rounded-lg p-6 w-full mb-6"
            ):
                tag("scan-db")
                ui.label("◆ 数据库同步").classes("text-lg font-mono text-cyan-400 mb-2")
                ui.label(
                    "扫描 From/To/Root 顶层影视文件与压缩包（不递归子目录），"
                    "记录来源，与数据库对比更新。"
                ).classes("text-sm text-slate-500 font-mono mb-4")

                _path_row(config_mgr, profile, "from", cfg.get("from", ""))
                _path_row(config_mgr, profile, "to", cfg.get("to", ""))
                _path_row(config_mgr, profile, "root", cfg.get("root", ""))

                with ui.row().classes("gap-4"):
                    run_button("▶ 对比差异", "cyan", lambda: _run_db_diff(config_mgr, profile, db))
                    run_button("▶ 数据库同步", "cyan", lambda: _run_db_sync(config_mgr, profile, db))

        build_log_panel()


def _path_row(config_mgr, profile, key, value):
    """一行路径输入：label 大写，输入即保存（root 额外刷新抽屉显示）。"""
    label = {"from": "From", "to": "To", "root": "Root"}[key]
    with ui.row().classes("gap-2 items-center w-full mb-3"):
        ui.label(f"{label}:").classes("text-xs text-slate-500 font-mono w-20")
        ui.input(value=value, placeholder="D:/Media/Movies").classes(
            "flex-1 font-mono text-xs"
        ).props("outlined dense dark").on_value_change(
            lambda e, k=key: _save_path(config_mgr, profile, k, e.value),
        )


def _save_path(config_mgr, profile, key, value):
    config_mgr.update_profile_config(profile, key, value or "")
    if key == "root":
        update_drawer_info()


async def _run_db_diff(config_mgr, profile, db):
    """对比 From/To/Root 顶层文件与数据库记录，展示增减清单（含来源）。"""
    clear_log()
    set_running("对比差异")
    log("◆ 开始对比数据库差异...", "cyan")

    if cancel_requested():
        log("◆ 用户取消", "yellow")
        set_ready()
        return

    try:
        diff = await asyncio.to_thread(
            diff_db, config_mgr.get_profile_config(profile), db, profile,
        )
    except Exception as e:
        logger.exception("对比数据库差异失败 profile=%s", profile)
        log(f"  对比失败: {e}", "red")
        set_error()
        return

    added = diff["added"]
    removed = diff["removed"]
    existing = diff["existing"]

    log(f"  + 新增 {len(added)} 个文件（磁盘有，DB 无）", "green")
    for f, source in added[:20]:
        log(f"      {f.name}  [{_SOURCE_LABEL.get(source, source)}]", "green")
    if len(added) > 20:
        log(f"      ... 还有 {len(added) - 20} 个", "gray")

    log(f"  - 移除 {len(removed)} 个文件（DB 有，磁盘无）", "red")
    for p in removed[:20]:
        log(f"      {Path(p).name}", "red")
    if len(removed) > 20:
        log(f"      ... 还有 {len(removed) - 20} 个", "gray")

    log(f"  = 保持不变 {existing} 个文件", "gray")

    if not added and not removed:
        log("  数据库与磁盘完全一致 ✓", "cyan")
    log("◆ 对比完成 ✓", "cyan")
    set_ready()


async def _run_db_sync(config_mgr, profile, db):
    """执行数据库同步：将 From/To/Root 新增文件写入 media 表（记录来源）。"""
    clear_log()
    set_running("数据库同步")
    log("◆ 开始数据库同步...", "cyan")

    if cancel_requested():
        log("◆ 用户取消", "yellow")
        set_ready()
        return

    try:
        diff = await asyncio.to_thread(
            diff_db, config_mgr.get_profile_config(profile), db, profile,
        )
        log(f"  发现 {len(diff['added'])} 个新增文件", "gray")

        if cancel_requested():
            log("◆ 用户取消", "yellow")
            set_ready()
            return

        count = await asyncio.to_thread(
            sync_db, config_mgr.get_profile_config(profile), db, profile,
            diff["added"],
        )
        log(f"  已写入 {count} 条新记录", "green")

        if diff["removed"]:
            log(
                f"  注意: {len(diff['removed'])} 个文件在磁盘已不存在，"
                f"数据库对应记录已保留",
                "yellow",
            )
    except Exception as e:
        logger.exception("数据库同步失败 profile=%s", profile)
        log(f"  数据库同步失败: {e}", "red")
        set_error()
        return

    log("◆ 数据库同步完成 ✓", "cyan")
    update_drawer_info()
    set_ready()

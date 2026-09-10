"""
扫描模块（screen）— 数据库同步。

对应原同步页的「数据库同步」卡片：扫描 Root（排除 from/to 若在 Root 下）
→ 与 media 表对比 → 更新数据库。

参数（输入即保存到 config_manager，跨模块共享）：
    root         — 扫描目录
    crid_pattern — crid 正则提取
"""

import asyncio

from pathlib import Path

from nicegui import ui

from core.logging_config import get_logger
from core.common.browser import get_relative_exclude_dirs
from ui.state import tag, update_drawer_info, cancel_requested
from ui.workspaces.screen._shared import (
    log, clear_log, set_running, set_ready, build_profile_radio, build_log_panel,
)

logger = get_logger(__name__)


def build_scan(config_mgr, db, registry):
    """构建扫描页 UI。"""
    profile = config_mgr.current_profile
    handler = registry.get(profile)
    cfg = config_mgr.get_profile_config()
    root = cfg.get("root", "") or "未设置"
    crid_pattern = cfg.get("crid_pattern", "")

    tag("scan")
    ui.label("◆ 扫描").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")
    build_profile_radio(config_mgr, "scan")

    if not handler:
        ui.label("⚠ 当前 Profile 未加载 handler").classes("text-red-400 font-mono")
        return

    with ui.row().classes("w-full").style("position: relative;"):
        with ui.column().classes("flex-1 min-w-0").style("margin-right: calc(38% + 1rem);"):
            with ui.card().classes(
                "bg-slate-950 border border-cyan-800 rounded-lg p-6 w-full mb-6"
            ):
                tag("scan-db")
                ui.label("◆ 数据库同步").classes("text-lg font-mono text-cyan-400 mb-2")
                ui.label(
                    "扫描 Root 中全部视频文件，与数据库记录对比，更新差异。"
                ).classes("text-sm text-slate-500 font-mono mb-4")

                with ui.row().classes("gap-2 items-center w-full mb-3"):
                    ui.label("Root:").classes("text-xs text-slate-500 font-mono w-20")
                    root_input = ui.input(value=cfg.get("root", ""), placeholder="D:/Media/Movies").classes(
                        "flex-1 font-mono text-xs"
                    ).props("outlined dense dark")
                    root_input.on_value_change(lambda e: _save_root(
                        config_mgr, profile, e.value,
                    ))

                with ui.row().classes("gap-2 items-center w-full mb-4"):
                    ui.label("crid 正则:").classes("text-xs text-slate-500 font-mono w-20")
                    crid_input = ui.input(
                        value=crid_pattern, placeholder="例如: CRID-(\\d+)",
                    ).classes("flex-1 font-mono text-xs").props("outlined dense dark")
                    crid_input.on_value_change(lambda e: (
                        config_mgr.update_profile_config(profile, "crid_pattern", e.value or "")
                    ))

                with ui.row().classes("gap-4"):
                    ui.button(
                        "▶ 对比差异",
                        on_click=lambda: _run_db_diff(handler),
                    ).classes(
                        "bg-cyan-900 hover:bg-cyan-700 text-cyan-300 font-mono "
                        "border border-cyan-600 rounded px-6 py-2"
                    )
                    ui.button(
                        "▶ 数据库同步",
                        on_click=lambda: _run_db_sync(handler),
                    ).classes(
                        "bg-blue-900 hover:bg-blue-700 text-blue-300 font-mono "
                        "border border-blue-600 rounded px-6 py-2"
                    )

        build_log_panel()


def _save_root(config_mgr, profile, value):
    config_mgr.update_profile_config(profile, "root", value or "")
    update_drawer_info()


def _exclude_dirs(handler) -> list[str]:
    """按当前配置计算 root 下需排除的相对目录（含 from/to）。"""
    cfg = handler.config
    return get_relative_exclude_dirs(
        cfg.get("root", ""), cfg.get("from", ""), cfg.get("to", ""),
    )


async def _run_db_diff(handler):
    """对比 Root 文件与数据库记录，展示增减清单。"""
    clear_log()
    set_running("对比差异")
    log("◆ 开始对比数据库差异...", "cyan")

    exclude_dirs = _exclude_dirs(handler)
    if exclude_dirs:
        log(f"  排除目录: {exclude_dirs}", "gray")

    if cancel_requested():
        log("◆ 用户取消", "yellow")
        set_ready()
        return

    try:
        diff = await asyncio.to_thread(
            handler.diff_db,
            exclude_dirs=exclude_dirs if exclude_dirs else None,
        )
    except Exception as e:
        logger.exception("对比数据库差异失败 profile=%s", handler.profile_name)
        log(f"  对比失败: {e}", "red")
        set_ready()
        return

    if cancel_requested():
        log("◆ 用户取消", "yellow")
        set_ready()
        return

    added = diff["added"]
    removed = diff["removed"]
    existing = diff["existing"]

    log(f"  + 新增 {len(added)} 个文件（Root 中有，DB 中无）", "green")
    for f in added[:20]:
        log(f"      {f.name}", "green")
    if len(added) > 20:
        log(f"      ... 还有 {len(added) - 20} 个", "gray")

    log(f"  - 移除 {len(removed)} 个文件（DB 中有，Root 中无）", "red")
    for p in removed[:20]:
        log(f"      {Path(p).name}", "red")
    if len(removed) > 20:
        log(f"      ... 还有 {len(removed) - 20} 个", "gray")

    log(f"  = 保持不变 {existing} 个文件", "gray")

    if not added and not removed:
        log("  数据库与 Root 完全一致 ✓", "cyan")
    log("◆ 对比完成 ✓", "cyan")
    set_ready()


async def _run_db_sync(handler):
    """执行数据库同步：将 Root 中新增文件写入 media 表。"""
    clear_log()
    set_running("数据库同步")
    log("◆ 开始数据库同步...", "cyan")

    crid_pattern = handler.config.get("crid_pattern", "")
    exclude_dirs = _exclude_dirs(handler)
    if crid_pattern:
        log(f"  crid 提取: {crid_pattern}", "gray")

    if cancel_requested():
        log("◆ 用户取消", "yellow")
        set_ready()
        return

    try:
        diff = await asyncio.to_thread(
            handler.diff_db,
            exclude_dirs=exclude_dirs if exclude_dirs else None,
        )
        log(f"  发现 {len(diff['added'])} 个新增文件", "gray")

        if cancel_requested():
            log("◆ 用户取消", "yellow")
            set_ready()
            return

        count = await asyncio.to_thread(
            handler.sync_db,
            exclude_dirs=exclude_dirs if exclude_dirs else None,
            crid_pattern=crid_pattern,
            added=diff["added"],
        )
        log(f"  已写入 {count} 条新记录", "green")

        if diff["removed"]:
            log(
                f"  注意: {len(diff['removed'])} 个文件在 Root 中已不存在，"
                f"数据库中对应记录已保留",
                "yellow",
            )
    except Exception as e:
        logger.exception("数据库同步失败 profile=%s", handler.profile_name)
        log(f"  数据库同步失败: {e}", "red")
        set_ready()
        return

    log("◆ 数据库同步完成 ✓", "cyan")
    update_drawer_info()
    set_ready()

"""字幕页（screen）— 检测 root 无字幕文件，射手搜索中英双字并下载到本地。"""

import asyncio
from pathlib import Path

from nicegui import ui

from core.logging_config import get_logger
from workspaces.screen.scan import media_files
from workspaces.screen.subtitle import (
    is_no_subtitle, search_keyword, search_subs, download_subs, SAVE_DIR,
)
from ui.state import tag
from ui.workspaces.screen._shared import (
    log, clear_log, set_running, set_ready, set_error,
    run_button, build_profile_radio, build_log_panel, mask_key,
)

logger = get_logger(__name__)


def build_subtitle(config_mgr, db, registry):
    """构建配字幕页 UI。"""
    profile = config_mgr.current_profile
    cfg = config_mgr.get_profile_config()

    tag("subtitle")
    ui.label("◆ 配字幕").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")
    build_profile_radio(config_mgr, "sub_download")

    with ui.row().classes("w-full").style("position: relative;"):
        with ui.column().classes("flex-1 min-w-0").style("margin-right: calc(38% + 1rem);"):
            with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-6 w-full mb-6"):
                tag("subtitle-config")
                ui.label("◆ 配字幕").classes("text-lg font-mono text-cyan-400 mb-2")
                ui.label(
                    "检测 root 中文件名标记「无字幕」的电影，射手搜索中英双字并下载到本地。"
                ).classes("text-sm text-slate-500 font-mono mb-3")

                token = cfg.get("subtitle_token", "")
                with ui.row().classes("gap-2 items-center w-full mb-3"):
                    ui.label("射手 Token:").classes("text-xs text-slate-500 font-mono w-24")
                    token_input = ui.input(
                        value=mask_key(token) if token else "",
                        placeholder="输入新 Token 覆盖",
                    ).props("outlined dense dark").classes("flex-1 font-mono text-xs").on_value_change(
                        lambda e: _save_token(config_mgr, profile, e.value or "", token_input),
                    )

                with ui.row().classes("gap-3"):
                    run_button("▶ 检测无字幕", "cyan", lambda: _detect(db, profile))
                    run_button(
                        "▶ 搜索并下载", "cyan",
                        lambda: _search_download(config_mgr, db, profile),
                    )

            table_container = ui.column().classes("w-full")

        build_log_panel()


def _save_token(config_mgr, profile, value, token_input):
    """录入射手 token：非空才覆盖保存，并刷新输入框为脱敏显示。"""
    if value:
        config_mgr.update_profile_config(profile, "subtitle_token", value)
        token_input.set_value(mask_key(value))


def _root_no_subtitle(db, profile) -> list[Path]:
    """root 中文件名标记「无字幕」且存在的文件。"""
    files = [f for f in media_files(db, profile, "root") if f.exists()]
    return [f for f in files if is_no_subtitle(f)]


async def _detect(db, profile):
    """检测无字幕：列出 root 中字幕槽=无字幕的文件。"""
    clear_log()
    set_running("检测无字幕")
    targets = await asyncio.to_thread(_root_no_subtitle, db, profile)
    log(f"  root 中「无字幕」文件 {len(targets)} 个", "cyan")
    for f in targets:
        log(f"    └ {f.name}", "gray")
    set_ready()


async def _search_download(config_mgr, db, profile):
    """搜索并下载：逐文件按中文名搜索，取首个中英双字下载到 SAVE_DIR。"""
    clear_log()
    set_running("搜索并下载")
    token = config_mgr.get_profile_config(profile).get("subtitle_token", "")
    if not token:
        log("  未设置射手 Token", "red")
        set_error()
        return
    targets = await asyncio.to_thread(_root_no_subtitle, db, profile)
    if not targets:
        log("  无「无字幕」文件", "yellow")
        set_ready()
        return
    ok = miss = 0
    for f in targets:
        kw = search_keyword(f)
        try:
            cands = await asyncio.to_thread(search_subs, token, kw)
        except Exception as e:
            logger.warning("搜索失败 %s: %s", kw, e)
            log(f"  ✗ {kw} 搜索失败: {e}", "red")
            miss += 1
            continue
        if not cands:
            log(f"  ✗ {kw} 无中英双字字幕", "yellow")
            miss += 1
            continue
        c = cands[0]
        try:
            saved = await asyncio.to_thread(download_subs, token, c["id"], f.stem)
        except Exception as e:
            logger.warning("下载失败 %s: %s", kw, e)
            log(f"  ✗ {kw} 下载失败: {e}", "red")
            miss += 1
            continue
        ok += 1
        for p in saved:
            log(f"  ✓ {kw} [{c['desc']}] → {Path(p).name}", "green")
    log(f"◆ 完成：下载 {ok} 个，失败/无 {miss} 个，保存于 {SAVE_DIR}", "cyan")
    set_ready()

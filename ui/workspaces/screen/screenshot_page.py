"""
截图模块（screen）— 截图采集。

对应原同步页的「截图采集」卡片：PyAV 截帧存入 screenshots 表，
后台线程逐文件处理，实时输出进度。

参数（输入即保存到 config_manager，跨模块共享）：
    root                       — 媒体目录（与扫描模块共享）
    screenshot_config.count    — 平均截取张数
    screenshot_config.moments  — 指定时间点（秒，逗号分隔）
"""

import asyncio

from pathlib import Path

from nicegui import ui

from core.logging_config import get_logger
from core.screenshots import capture_one_video
from ui.state import tag, update_drawer_info, cancel_requested
from ui.workspaces.screen._shared import (
    log, clear_log, set_running, set_ready, build_profile_radio, build_log_panel,
)

logger = get_logger(__name__)


def build_screenshot(config_mgr, db, registry):
    """构建截图页 UI。"""
    profile = config_mgr.current_profile
    handler = registry.get(profile)
    cfg = config_mgr.get_profile_config()
    ss_cfg = cfg.get("screenshot_config", {})
    moments_str = ", ".join(str(m) for m in ss_cfg.get("moments", []))

    tag("screenshot")
    ui.label("◆ 截图").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")
    build_profile_radio(config_mgr, "screenshot")

    if not handler:
        ui.label("⚠ 当前 Profile 未加载 handler").classes("text-red-400 font-mono")
        return

    with ui.row().classes("w-full").style("position: relative;"):
        with ui.column().classes("flex-1 min-w-0").style("margin-right: calc(38% + 1rem);"):
            with ui.card().classes(
                "bg-slate-950 border border-cyan-800 rounded-lg p-6 w-full mb-6"
            ):
                tag("screenshot-config")
                ui.label("◆ 截图采集").classes("text-lg font-mono text-cyan-400 mb-2")
                ui.label(
                    "使用 PyAV 从视频文件中提取帧截图，存入 screenshots 表。"
                    "后台线程逐文件处理，实时显示进度。"
                ).classes("text-sm text-slate-500 font-mono mb-4")

                with ui.row().classes("gap-2 items-center w-full mb-3"):
                    ui.label("Root:").classes("text-xs text-slate-500 font-mono w-20")
                    ui.input(value=cfg.get("root", ""), placeholder="D:/Media/Movies").classes(
                        "flex-1 font-mono text-xs"
                    ).props("outlined dense dark").on_value_change(
                        lambda e: _save_root(config_mgr, profile, e.value),
                    )

                with ui.row().classes("gap-2 items-center w-full mb-3"):
                    ui.label("count:").classes("text-xs text-slate-500 font-mono w-20")
                    ui.number(
                        value=ss_cfg.get("count", 3), min=1, max=99, precision=0,
                    ).classes("w-32 font-mono text-xs").props("outlined dense dark").on_value_change(
                        lambda e: _set_ss(
                            config_mgr, profile, "count", int(e.value or 3),
                        ),
                    )
                    ui.label("moments 非空时忽略 count").classes(
                        "text-xs text-slate-600 font-mono"
                    )

                with ui.row().classes("gap-2 items-center w-full mb-4"):
                    ui.label("moments:").classes("text-xs text-slate-500 font-mono w-20")
                    ui.input(
                        value=moments_str, placeholder="例如: 30, 60, 120（秒，留空为均分）",
                    ).classes("flex-1 font-mono text-xs").props("outlined dense dark").on_value_change(
                        lambda e: _set_ss(
                            config_mgr, profile, "moments", _parse_moments(e.value),
                        ),
                    )

                ui.button(
                    "▶ 截取截图",
                    on_click=lambda: _run_capture_screenshots(handler),
                ).classes(
                    "bg-purple-900 hover:bg-purple-700 text-purple-300 font-mono "
                    "border border-purple-600 rounded px-6 py-2"
                )

        build_log_panel()


def _save_root(config_mgr, profile, value):
    config_mgr.update_profile_config(profile, "root", value or "")
    update_drawer_info()


def _set_ss(config_mgr, profile, field, value):
    ss = dict(config_mgr.get_profile_config(profile).get("screenshot_config", {}))
    ss[field] = value
    config_mgr.update_profile_config(profile, "screenshot_config", ss)


def _parse_moments(s: str) -> list[float]:
    parts = [p.strip() for p in (s or "").replace("，", ",").split(",") if p.strip()]
    result = []
    for p in parts:
        try:
            result.append(float(p))
        except ValueError:
            continue
    return result


async def _run_capture_screenshots(handler):
    """逐文件后台截取，实时输出进度，不阻塞 UI。"""
    from ui.state import status_progress

    clear_log()
    set_running("截取截图")
    log("◆ 开始截图采集...", "cyan")

    try:
        cfg = handler.config
        ss_cfg = cfg.get("screenshot_config", {})
        count = ss_cfg.get("count", 3)
        moments = ss_cfg.get("moments", [])

        log("  读取媒体记录...", "gray")
        records = handler.db.get_media_by_profile(handler.profile_name)
        log(f"  共 {len(records)} 条记录", "gray")

        if not records:
            log("  无媒体记录", "yellow")
            set_ready()
            return

        log("  预过滤已有截图...", "gray")
        pending = []
        skipped = 0
        for rec in records:
            existing = handler.db.get_screenshot_count(rec["mv_path"])
            if existing >= count:
                skipped += 1
            else:
                pending.append(rec)

        if skipped:
            log(f"  ⊘ 跳过 {skipped} 个（截图已达 {count} 张上限）", "gray")
        log(f"  待处理 {len(pending)} 个", "cyan")

        if not pending:
            log("  全部视频截图已达标，无需处理 ✓", "green")
            set_ready()
            return

        total = 0
        VIDEO_TIMEOUT = 120
        for i, rec in enumerate(pending):
            if cancel_requested():
                log("◆ 用户取消", "yellow")
                break
            mv_path = rec["mv_path"]
            name = Path(mv_path).name
            log(f"  [{i+1}/{len(pending)}] {name}", "cyan")
            if status_progress:
                status_progress.set_value((i + 1) / len(pending))

            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        capture_one_video, handler.db, mv_path, handler.profile_name,
                        count, moments, cancel_requested,
                    ),
                    timeout=VIDEO_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning("截图超时: %s", mv_path)
                log(f"  {name}: 超时（>{VIDEO_TIMEOUT}s）", "red")
                continue
            except Exception as e:
                logger.exception("截图失败: %s", mv_path)
                log(f"  {name}: 失败 - {e}", "red")
                continue

            cnt = result.get("count", 0)
            total += cnt
            status = result.get("status", "?")
            if cnt > 0 and "失败" not in status:
                color = "green"
            elif cnt == 0 and ("—" in status):
                color = "red"
            else:
                color = "yellow"
            log(f"  {name}: {status}", color)

        log(f"◆ 截图采集完成: 共 {total} 张 ✓", "cyan")
    except Exception as e:
        import traceback
        logger.exception("截图采集异常 profile=%s", handler.profile_name)
        log(f"◆ 截图采集异常: {e}", "red")
        log(traceback.format_exc(), "red")
    finally:
        set_ready()

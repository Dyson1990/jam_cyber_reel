"""DTS 检测页（lab）— 扫描目录下视频，标记哪些封装了 DTS 音轨。"""

import asyncio
from pathlib import Path

from nicegui import run, ui

from core.files import scan_videos
from ui.state import tag
from workspaces.lab.dts import detect_file


def build_dts(config_mgr, db, registry):
    """构建 DTS 检测页 UI。"""
    root = config_mgr.get_profile_root() or ""

    tag("dts")
    ui.label("◆ DTS 专利音轨检测").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")
    ui.label(
        "移动端播放器提示「需购买 DTS 专利授权」时，检测目录下哪些视频封装了 DTS 音轨。"
    ).classes("text-sm text-slate-500 font-mono mb-4")

    with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-4 w-full mb-4"):
        with ui.row().classes("gap-2 items-center w-full"):
            ui.label("目录:").classes("text-xs text-slate-500 font-mono w-10")
            path_input = ui.input(value=root, placeholder="D:/Media/Movies").classes(
                "flex-1 font-mono text-xs"
            ).props("outlined dense dark")

            async def _browse():
                p = await run.io_bound(_pick_dir, path_input.value)
                if p:
                    path_input.set_value(p)

            ui.button("浏览", on_click=_browse).props("outline dense dark")
        with ui.row().classes("gap-4 mt-3 items-center"):
            run_btn = ui.button("▶ 检测 DTS", on_click=None).classes(
                "font-mono px-6 py-2 bg-cyan-900 hover:bg-cyan-700 text-cyan-300 "
                "border border-cyan-600 rounded"
            )
            summary_label = ui.label("").classes("text-sm font-mono text-slate-400")

    result = ui.column().classes("w-full gap-2")

    async def _run():
        directory = path_input.value.strip()
        if not directory:
            summary_label.set_text("请先填写扫描目录")
            return
        run_btn.set_enabled(False)
        result.clear()
        try:
            files = await asyncio.to_thread(scan_videos, Path(directory))
        except Exception as e:
            summary_label.set_text(f"扫描失败: {e}")
            run_btn.set_enabled(True)
            return
        if not files:
            summary_label.set_text("目录下无视频文件")
            run_btn.set_enabled(True)
            return

        summary_label.set_text(f"扫描中… 共 {len(files)} 个文件")
        rows, dts_count = [], 0
        for f in files:
            r = await asyncio.to_thread(detect_file, str(f))
            if r["error"]:
                rows.append({"file": Path(r["path"]).name, "dts": "⚠ 打开失败", "audio": r["error"]})
                continue
            if r["has_dts"]:
                dts_count += 1
                rows.append({"file": Path(r["path"]).name, "dts": "● DTS", "audio": _streams(r)})
            else:
                rows.append({"file": Path(r["path"]).name, "dts": "○ 无", "audio": _streams(r)})

        with result:
            ui.table(
                columns=[
                    {"name": "file", "label": "文件", "field": "file", "align": "left"},
                    {"name": "dts", "label": "DTS", "field": "dts", "align": "left"},
                    {"name": "audio", "label": "音轨", "field": "audio", "align": "left"},
                ],
                rows=rows,
            ).classes("w-full")
        summary_label.set_text(f"共 {len(files)} 个文件，{dts_count} 个含 DTS 音轨")
        run_btn.set_enabled(True)

    run_btn.on_click(_run)


def _streams(r: dict) -> str:
    """把单文件的音频流压缩成一行摘要。"""
    if not r["streams"]:
        return "无音轨"
    parts = []
    for s in r["streams"]:
        label = s["codec"] or "?"
        if s["profile"]:
            label += f" ({s['profile']})"
        if s["language"]:
            label += f" [{s['language']}]"
        parts.append(label)
    return " / ".join(parts)


def _pick_dir(initial: str):
    """原生目录选择器（阻塞，运行于后台线程），返回所选路径或 None。"""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askdirectory(initialdir=initial or None)
    root.destroy()
    return path or None

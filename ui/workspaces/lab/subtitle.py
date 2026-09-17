"""字幕提取页（lab）— 列出视频封装的字幕流，文本字幕提取为 SRT 并可保存。"""

import asyncio
from pathlib import Path

from nicegui import run, ui

from ui.state import tag
from workspaces.lab.subtitle import list_subtitle_streams, extract_srt

_KIND_LABEL = {"text": "文本", "bitmap": "图形", "unknown": "未知"}


def build_subtitle(config_mgr, db, registry):
    """构建字幕提取页 UI。"""
    tag("subtitle")
    ui.label("◆ 字幕提取").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")
    ui.label(
        "直接读取视频文件封装的字幕流；文本字幕转 SRT，图形字幕（PGS/VobSub）仅标注类型。"
    ).classes("text-sm text-slate-500 font-mono mb-4")

    with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-4 w-full mb-4"):
        with ui.row().classes("gap-2 items-center w-full"):
            ui.label("文件:").classes("text-xs text-slate-500 font-mono w-10")
            path_input = ui.input(placeholder="D:/Media/Movies/a.mkv").classes(
                "flex-1 font-mono text-xs"
            ).props("outlined dense dark")

            async def _browse():
                p = await run.io_bound(_pick_file, path_input.value)
                if p:
                    path_input.set_value(p)

            ui.button("浏览", on_click=_browse).props("outline dense dark")
        with ui.row().classes("gap-4 mt-3 items-center"):
            run_btn = ui.button("▶ 分析字幕", on_click=None).classes(
                "font-mono px-6 py-2 bg-cyan-900 hover:bg-cyan-700 text-cyan-300 "
                "border border-cyan-600 rounded"
            )
            status_label = ui.label("").classes("text-sm font-mono text-slate-400")

    result = ui.column().classes("w-full gap-3")

    async def _run():
        path = path_input.value.strip()
        if not path or not Path(path).exists():
            status_label.set_text("请填写有效视频文件路径")
            return
        run_btn.set_enabled(False)
        result.clear()
        try:
            streams = await asyncio.to_thread(list_subtitle_streams, path)
        except Exception as e:
            status_label.set_text(f"打开失败: {e}")
            run_btn.set_enabled(True)
            return
        if not streams:
            with result:
                ui.label("该文件未封装字幕流").classes(
                    "text-slate-400 font-mono text-sm"
                )
            status_label.set_text("无字幕流")
            run_btn.set_enabled(True)
            return

        with result:
            rows = [
                {
                    "#": s["pos"],
                    "codec": s["codec"] or "?",
                    "lang": s["language"],
                    "kind": _KIND_LABEL.get(s["kind"], s["kind"]),
                }
                for s in streams
            ]
            ui.table(
                columns=[
                    {"name": "#", "label": "#", "field": "#", "align": "left"},
                    {"name": "codec", "label": "编码", "field": "codec", "align": "left"},
                    {"name": "lang", "label": "语言", "field": "lang", "align": "left"},
                    {"name": "kind", "label": "类型", "field": "kind", "align": "left"},
                ],
                rows=rows,
            ).classes("w-full")

            for s in streams:
                if s["kind"] != "text":
                    continue
                srt, err = await asyncio.to_thread(extract_srt, path, s["pos"])
                title = f"字幕流 {s['pos']} — {s['codec']}"
                if s["language"]:
                    title += f" [{s['language']}]"
                with ui.card().classes(
                    "bg-slate-950 border border-cyan-800 rounded-lg p-4 w-full"
                ):
                    ui.label(title).classes("text-sm font-mono text-cyan-400 mb-2")
                    if err:
                        ui.label(err).classes("text-orange-400 font-mono text-sm")
                        continue
                    ui.textarea(value=srt).classes(
                        "w-full font-mono text-xs text-slate-300"
                    ).style("min-height: 200px;")
                    save_status = ui.label("").classes("text-xs font-mono mt-2")
                    ui.button(
                        "保存为 .srt",
                        on_click=lambda _, _srt=srt, _path=path, _s=s: _save_srt(
                            _path, _srt, _s, save_status
                        ),
                    ).classes(
                        "bg-slate-800 hover:bg-slate-700 text-cyan-300 font-mono "
                        "border border-cyan-700 rounded px-4 py-1 text-xs"
                    )

        status_label.set_text(f"共 {len(streams)} 条字幕流")
        run_btn.set_enabled(True)

    run_btn.on_click(_run)


def _save_srt(path: str, srt: str, s, status_label):
    """保存 SRT 到同目录 <stem>.<lang>.srt（无语言用流序号）。"""
    stem = Path(path).stem
    tag_name = s["language"] or f"stream{s['pos']}"
    out = Path(path).with_name(f"{stem}.{tag_name}.srt")
    out.write_text(srt, encoding="utf-8")
    status_label.set_text(f"已保存 {out.name} ✓")
    status_label.classes("text-blue-400 text-xs font-mono mt-2")


def _pick_file(initial: str):
    """原生文件选择器（阻塞，运行于后台线程），返回所选路径或 None。"""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askopenfilename(
        title="选择视频文件",
        initialdir=initial or None,
        filetypes=[("视频", "*.mp4 *.mkv *.avi *.mov *.wmv *.ts"), ("所有文件", "*.*")],
    )
    root.destroy()
    return path or None

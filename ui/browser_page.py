"""
媒体浏览器模块 - 浏览 Root 路径下的媒体数据。

文件作用：
    从 data.db 读取媒体记录，只显示 Root 路径下的视频。
    按 mv_path 分组展示，支持分组折叠/展开。
    每行显示封面、标题、动态列、截图缩略图。

与其它模块的关系：
    - 被 ui/layout.py 的 switch_page("browser") 调用
    - 通过 Database 读取 media_{profile} 表
    - 系列、导演字段预留超链接接口

主要函数：
    build_browser(config_mgr, db) - 构建媒体浏览器 UI
"""

import base64
import os
from collections import defaultdict
from pathlib import Path

from nicegui import ui


def _get_exclude_dirs(root: str, *sub_paths: str) -> list[str]:
    """若 sub_path 在 root 下，返回其相对路径首段作为排除目录前缀。"""
    if not root:
        return []
    root_norm = os.path.normpath(root).lower()
    result: list[str] = []
    for sp in sub_paths:
        if not sp:
            continue
        sp_norm = os.path.normpath(sp).lower()
        if sp_norm.startswith(root_norm) and sp_norm != root_norm:
            result.append(sp_norm)
    return result


def build_browser(config_mgr, db):
    """构建媒体浏览器 UI，仅显示 Root 路径下的视频。

    数据流：
        1. db.get_media_by_profile(profile) 获取全部媒体记录
        2. 过滤：仅保留 mv_path 在 root 目录下且不在 from/to 下的记录
        3. 按 mv_path 的父目录分组
        4. 渲染分组树：每组默认折叠，点击展开
        5. 列由 table_schema 配置动态决定
    """
    profile = config_mgr.current_profile
    cfg = config_mgr.get_profile_config()
    table_schema = cfg.get("table_schema", [])
    root = cfg.get("root", "")

    ui.label("◆ MEDIA BROWSER").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")
    ui.label(f"Profile: {profile}  |  Root: {root or '未设置'}").classes(
        "text-sm text-gray-500 font-mono mb-4"
    )

    records = db.get_media_by_profile(profile)

    # 过滤：仅 root 路径下的视频，排除 from/to 目录
    root_mismatch = False
    if root and records:
        root_norm = os.path.normpath(root).lower()
        exclude_prefixes = _get_exclude_dirs(root, cfg.get("from", ""), cfg.get("to", ""))
        filtered = []
        for r in records:
            rp = os.path.normpath(r["mv_path"]).lower()
            if not rp.startswith(root_norm):
                continue
            if any(rp.startswith(ep) for ep in exclude_prefixes):
                continue
            filtered.append(r)
        if filtered:
            records = filtered
        else:
            root_mismatch = True

    if not records:
        with ui.card().classes("bg-gray-950 border border-cyan-800 rounded-lg p-6 w-full"):
            ui.label("暂无媒体数据").classes("text-gray-500 font-mono")
            ui.label("请先在 Sync 页面执行同步").classes("text-gray-600 font-mono text-sm mt-2")
        return

    if root_mismatch:
        ui.label(f"⚠ Root 不匹配任何记录，显示全部 {len(records)} 条").classes(
            "text-sm text-yellow-400 font-mono mb-2")
    else:
        with ui.row().classes("w-full items-center gap-4 mb-4"):
            ui.label(f"共 {len(records)} 条记录").classes(
                "text-sm text-gray-400 font-mono")
            ui.button("📷 加载封面", on_click=lambda: render_table(with_covers=True)).classes(
                "bg-cyan-900 hover:bg-cyan-700 text-cyan-300 font-mono text-sm "
                "border border-cyan-600 rounded px-4 py-1")

    # 表格容器必须在按钮行之后创建，确保渲染在其下方
    table_container = ui.column().classes("w-full")

    def render_table(with_covers: bool = False):
        table_container.clear()
        with table_container:
            _render_flat_table(records, table_schema, db, load_covers=with_covers)

    # 初次渲染不含封面（占位符）
    render_table(with_covers=False)


def _render_flat_table(records: list, table_schema: list[dict], db, load_covers: bool = False):
    """渲染平铺表格（无折叠），按路径分组显示分隔行。"""
    # 按父目录排序
    records = sorted(records, key=lambda r: (str(Path(r["mv_path"]).parent), r["title"] or ""))

    # 仅展示指定列
    show_cols = {"year", "file_size", "duration"}
    visible_cols = [c for c in table_schema if c["name"] in show_cols]

    # 表头
    with ui.row().classes(
        "w-full gap-2 py-2 border-b border-gray-700 text-xs text-gray-500 font-mono mb-2"
    ):
        ui.label("Cover").style("width: 86px;")
        ui.label("Title").style("flex: 2;")
        for col in visible_cols:
            ui.label(col.get("label", col["name"])).style("flex: 1;")
        ui.label("Shots").style("width: 80px;")

    for item in records:
        _render_media_row(item, visible_cols, db, load_covers=load_covers)


def _render_media_row(item, table_schema: list[dict], db, load_covers: bool = False):
    """渲染单条媒体记录行。"""
    with ui.row().classes("w-full gap-2 py-1 items-center hover:bg-gray-800 rounded"):

        # 封面图：仅在 load_covers=True 时加载 BLOB
        if load_covers:
            cover_bytes = item["cover"]
            if not cover_bytes:
                cover_bytes = db.get_cover_screenshot(item["mv_path"])

            if cover_bytes:
                b64 = base64.b64encode(cover_bytes).decode()
                ui.html(
                    f'<img src="data:image/png;base64,{b64}" loading="lazy" '
                    f'style="width:72px;height:96px;object-fit:cover;border:1px solid #0ff3;">'
                ).style("width: 86px;")
            else:
                _placeholder_cover()
        else:
            _placeholder_cover()

        # 标题
        ui.label(item["title"] or "—").classes("text-sm font-mono text-gray-200").style(
            "flex: 2; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"
        )

        # 动态列
        for col in table_schema:
            col_name = col["name"]
            value = item[col_name] if col_name in item.keys() else None
            display = _format_cell(value, col)
            cell = ui.label(display)
            cell.classes("text-sm font-mono text-gray-400").style("flex: 1;")
            if col_name in ("series", "director"):
                cell.classes(
                    "text-sm font-mono text-cyan-400 underline cursor-pointer",
                    remove="text-gray-400",
                )

        # 截图按钮
        _render_shot_btn(item["mv_path"], db)


def _render_shot_btn(mv_path: str, db):
    """渲染截图查看按钮，点击时临时加载截图数据。"""
    shot_cnt = db.get_screenshot_count(mv_path)
    if not shot_cnt:
        ui.label("—").classes("text-xs text-gray-600 font-mono").style("width: 80px;")
        return

    def open_viewer():
        shots = db.get_screenshots(mv_path)
        if not shots:
            return
        with ui.dialog() as viewer_dlg:
            viewer_dlg.props("full-width")
            viewer_dlg.props("full-height")
            viewer_dlg.open()
            with ui.card().classes("bg-gray-900 border border-cyan-700 rounded-lg p-4 w-full"):
                with ui.row().classes("w-full justify-between items-center mb-3"):
                    ui.label(f"◆ {Path(mv_path).name}").classes(
                        "text-lg font-mono text-cyan-400"
                    )
                    ui.button("✕", on_click=lambda: viewer_dlg.close()).classes(
                        "bg-gray-800 hover:bg-red-900 text-gray-400 font-mono text-xs border border-gray-700 rounded px-2 py-1"
                    )
                ui.label(f"共 {len(shots)} 张 · 点击图片放大").classes(
                    "text-xs text-gray-500 font-mono mb-4"
                )
                with ui.row().classes("flex-wrap gap-3 justify-center"):
                    for s in shots:
                        try:
                            full_b64 = base64.b64encode(s["image"]).decode()
                            label = s["time_label"] or f"{s['time_point']:.1f}s"

                            def _make_zoom(fb64=full_b64, lbl=label):
                                def open_zoom():
                                    with ui.dialog() as zoom_dlg:
                                        zoom_dlg.props("full-width")
                                        zoom_dlg.props("full-height")
                                        zoom_dlg.open()
                                        with ui.card().classes("bg-black border border-gray-700 rounded-lg p-2"):
                                            with ui.row().classes("w-full justify-end mb-1"):
                                                ui.button("✕", on_click=lambda: zoom_dlg.close()).classes(
                                                    "bg-gray-900 hover:bg-red-900 text-gray-400 font-mono text-xs "
                                                    "border border-gray-700 rounded px-2 py-1"
                                                )
                                            click_area = ui.element("div").classes("w-full h-full").style(
                                                "cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;"
                                            )
                                            with click_area:
                                                ui.html(
                                                    f'<img src="data:image/png;base64,{fb64}" '
                                                    f'style="max-width:88vw;max-height:78vh;object-fit:contain;">'
                                                )
                                                ui.label(f"{lbl}（点任意处关闭）").classes(
                                                    "text-xs font-mono text-gray-500 mt-2"
                                                )
                                            click_area.on("click", lambda: zoom_dlg.close())
                                return open_zoom

                            with ui.card().classes(
                                "bg-gray-800 border border-gray-700 rounded p-2 cursor-pointer "
                                "hover:border-cyan-400 transition-colors"
                            ):
                                ui.html(
                                    f'<img src="data:image/png;base64,{full_b64}" '
                                    f'style="width:200px;height:150px;object-fit:contain;" '
                                    f'title="点击放大">'
                                )
                                ui.label(label).classes(
                                    "text-xs text-gray-500 font-mono text-center mt-1"
                                )
                                ui.button("🔍", on_click=_make_zoom()).classes(
                                    "bg-transparent hover:bg-cyan-900 text-cyan-400 text-xs "
                                    "border-none rounded px-1 py-0 mx-auto"
                                )
                        except Exception:
                            pass

    btn = ui.button(f"📷 {shot_cnt}", on_click=open_viewer)
    btn.classes("bg-gray-800 hover:bg-cyan-900 text-cyan-300 text-xs font-mono "
                "border border-gray-700 rounded px-2 py-1")
    btn.style("width: 80px;")


def _format_cell(value, col: dict) -> str:
    """根据列类型格式化单元格显示值。"""
    if value is None:
        return "—"
    col_type = col.get("type", "TEXT")
    if col_type == "INTEGER" and col["name"] == "file_size":
        return _format_size(int(value))
    if col_type in ("REAL",) and isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _placeholder_cover():
    """生成封面占位符（纯色方块）。"""
    ui.html(
        '<div style="width:72px;height:96px;background:#1a1a2e;'
        'border:1px solid #333;display:flex;align-items:center;'
        'justify-content:center;color:#555;font-size:10px;">N/A</div>'
    ).style("width: 86px;")


def _format_size(size_bytes: int) -> str:
    """将字节数格式化为人类可读的文件大小。"""
    if size_bytes <= 0:
        return "—"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} B"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"

"""
知识库模块（screen）— chromadb 映射浏览 + AI 扩充。

展示：表格列出 chromadb 中「中文名/英文名/年份/豆瓣评分」，顶部可选
      「综合（自纠错结果）」或「豆瓣」两种视图。
扩充：输入 path 点「更新」，递归遍历 path 下视频与压缩包（含子文件夹），
      AI 提取文件名中的中英文名，去重后逐条走数据源固化进知识库。
"""

import asyncio

from pathlib import Path

from nicegui import ui

from core.files import VIDEO_EXTENSIONS
from core.logging_config import get_logger
from workspaces.screen.config import get_deepseek_key
from workspaces.screen.kb import kb_list, kb_lookup, kb_upsert
from workspaces.screen.sources.douban import parse_apizero
from ui.state import tag
from ui.workspaces.screen._shared import (
    log, clear_log, set_running, set_ready, set_error,
    run_button, build_profile_radio, build_log_panel,
)

logger = get_logger(__name__)

_ARCHIVE_EXT = {".zip", ".rar", ".7z"}


def _scan_media(root: Path) -> list[Path]:
    """递归遍历 root 下视频与压缩包（含子文件夹），去重排序。"""
    if not root or not root.is_dir():
        return []
    exts = VIDEO_EXTENSIONS | _ARCHIVE_EXT
    return sorted({f for f in root.rglob("*") if f.is_file() and f.suffix.lower() in exts})


def _table_rows(mode: str) -> list[dict]:
    """取表格行。豆瓣=只看含豆瓣一手数据的条目并展示豆瓣字段；综合=全部条目最终值。"""
    rows = []
    for e in kb_list():
        if mode == "douban":
            apz = ((e.get("raw") or {}).get("douban") or {}).get("apizero")
            if not isinstance(apz, dict):
                continue
            d = parse_apizero(apz)
            if not d:
                continue
            rows.append({
                "zh": d.get("zh", ""), "en": d.get("en", ""),
                "year": d.get("year", ""), "score": d.get("score", ""),
            })
        else:
            rows.append({
                "zh": e.get("zh", ""), "en": e.get("en", ""),
                "year": e.get("year", ""), "score": e.get("score", ""),
            })
    return rows


def build_kb(config_mgr, db, registry):
    """构建知识库页 UI。"""
    profile = config_mgr.current_profile
    cfg = config_mgr.get_profile_config()

    tag("kb")
    ui.label("◆ 知识库").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")
    build_profile_radio(config_mgr, "kb")

    with ui.row().classes("w-full").style("position: relative;"):
        with ui.column().classes("flex-1 min-w-0").style("margin-right: calc(38% + 1rem);"):
            with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-6 w-full mb-6"):
                tag("kb-config")
                ui.label("◆ 知识库扩充").classes("text-lg font-mono text-cyan-400 mb-2")

                mode_radio = ui.radio(
                    {"all": "综合（自纠错结果）", "douban": "豆瓣"},
                    value="all",
                ).props("inline").classes("mb-3 text-cyan-300")

                with ui.row().classes("gap-2 items-center w-full mb-3"):
                    ui.label("Path:").classes("text-xs text-slate-500 font-mono w-20")
                    path_input = ui.input(
                        value=cfg.get("kb_path", ""), placeholder="D:/Media/Movies",
                    ).classes("flex-1 font-mono text-xs").props("outlined dense dark").on_value_change(
                        lambda e: config_mgr.update_profile_config(
                            profile, "kb_path", e.value or "",
                        ),
                    )

                run_button(
                    "▶ 更新", "cyan",
                    lambda: _run_update(
                        config_mgr, profile, path_input.value, mode_radio.value, _render_table,
                    ),
                )

            with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-6 w-full mb-6"):
                tag("kb-manual")
                ui.label("◆ 人工更新").classes("text-lg font-mono text-cyan-400 mb-2")
                with ui.row().classes("gap-2 items-center w-full"):
                    zh_input = ui.input(placeholder="中文名").classes(
                        "flex-1 font-mono text-xs").props("outlined dense dark")
                    en_input = ui.input(placeholder="英文名").classes(
                        "flex-1 font-mono text-xs").props("outlined dense dark")
                    year_input = ui.input(placeholder="年份").classes(
                        "w-24 font-mono text-xs").props("outlined dense dark")
                    score_input = ui.input(placeholder="豆瓣评分(可空)").classes(
                        "w-32 font-mono text-xs").props("outlined dense dark")
                    ui.button("✔ 保存", on_click=lambda: _manual_save()).classes(
                        "bg-cyan-900 hover:bg-cyan-700 text-cyan-300 font-mono text-sm "
                        "border border-cyan-600 rounded px-4 py-1"
                    )

            with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-6 w-full"):
                tag("kb-table")
                ui.label("◆ 映射表").classes("text-lg font-mono text-cyan-400 mb-2")
                table_container = ui.column().classes("w-full")

        build_log_panel()

    def _render_table():
        if table_container.is_deleted:
            return
        table_container.clear()
        with table_container:
            rows = _table_rows(mode_radio.value)
            if not rows:
                ui.label("(知识库为空)").classes("text-xs text-slate-500 font-mono")
                return
            ui.table(
                columns=[
                    {"name": "zh", "label": "中文名", "field": "zh", "align": "left"},
                    {"name": "en", "label": "英文名", "field": "en", "align": "left"},
                    {"name": "year", "label": "年份", "field": "year", "align": "left"},
                    {"name": "score", "label": "豆瓣评分", "field": "score", "align": "left"},
                ],
                rows=rows,
            ).classes("w-full")

    def _manual_save():
        """人工补充数据源缺失：直接写入知识库（title 留空，id 由中文名>英文名派生）。"""
        zh = (zh_input.value or "").strip()
        en = (en_input.value or "").strip()
        year = (year_input.value or "").strip()
        score = (score_input.value or "").strip()
        if not zh and not en:
            ui.notify("中文名 / 英文名至少填一个", type="warning")
            return
        kb_upsert(zh, en, year, score, "")
        zh_input.value = en_input.value = year_input.value = score_input.value = ""
        _render_table()
        ui.notify("已写入知识库", type="positive")

    mode_radio.on_value_change(lambda e: _render_table())
    _render_table()


async def _run_update(config_mgr, profile, path_value, mode, render_cb):
    """更新知识库：遍历 path → AI 提取中英名 → 去重后逐条 fetch_info 固化。

    mode: "douban" 仅豆瓣源；"all" 仅豆瓣之外的其它源自纠错。
    """
    # 惰性导入：ai_naming 拖 LangChain、sources 拖 chromadb，只在真正更新时才加载
    from workspaces.screen.ai_naming import extract_names
    from workspaces.screen.sources import fetch_info, reset_breakers, SEARCH_DELAY

    clear_log()
    set_running("更新知识库")
    reset_breakers()
    path = Path(path_value or "")
    if not path or not path.is_dir():
        log("  Path 未设置或目录不存在", "red")
        set_error()
        return

    files = await asyncio.to_thread(_scan_media, path)
    if not files:
        log("  Path 下无视频/压缩文件", "yellow")
        set_ready()
        return
    names = [f.name for f in files]
    log(f"  扫描到 {len(names)} 个文件（含子文件夹）", "gray")

    cfg = config_mgr.get_profile_config(profile)
    key = get_deepseek_key(config_mgr)
    if not key:
        log("  未设置 Deepseek Key（请先到「概览」设置）", "red")
        set_error()
        return
    tmdb_key = cfg.get("tmdb_api_key", "")
    log(f"◆ 数据源模式：{'豆瓣' if mode == 'douban' else '综合（豆瓣外源）'}", "cyan")

    # AI 分块提取中英文名
    batch = int(cfg.get("ai_batch_size", 20)) or 20
    extracted: dict[str, dict] = {}
    log("◆ AI 提取文件名中的中英文名 ...", "cyan")
    for i in range(0, len(names), batch):
        chunk = names[i:i + batch]
        try:
            part = await asyncio.to_thread(extract_names, key, chunk)
        except Exception as e:
            logger.exception("AI 提取失败")
            log(f"  AI 提取失败: {e}", "red")
            set_error()
            return
        extracted.update(part)

    added = skipped = 0
    for name in names:
        ext = extracted.get(name) or {}
        zh = (ext.get("zh") or "").strip()
        en = (ext.get("en") or "").strip()
        q = zh or en
        if not q:
            log(f"  └ 跳过（未提取到片名）: {name}", "gray")
            skipped += 1
            continue
        # 去重：库中已命中该片名则不再提交
        if kb_lookup(q):
            skipped += 1
            continue
        try:
            info = await asyncio.to_thread(fetch_info, q, tmdb_key, mode)
        except Exception as e:
            logger.warning("取信息失败 %s: %s", q, e)
            info = None
        if info:
            added += 1
            log(
                f"  + {q} → {info.get('zh','')}/{info.get('en','')}/{info.get('year','')}",
                "green",
            )
        else:
            skipped += 1
            log(f"  └ 未命中数据源: {q}", "gray")
        await asyncio.sleep(SEARCH_DELAY)  # 限流，避免 apizero 429

    log(f"◆ 完成：新增 {added} 条，跳过 {skipped} 条", "cyan")
    render_cb()
    set_ready()

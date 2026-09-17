"""
知识库模块（screen）— chromadb 映射浏览 + AI 扩充。

展示：表格列出 chromadb 中「中文名/英文名/年份/豆瓣评分」，顶部可选
      「综合（自纠错结果）」或「豆瓣」两种视图。
扩充：点「更新」，从数据库中取 from/to/root 全部媒体文件路径，
      AI 提取文件名中的中英文名，去重后逐条走数据源固化进知识库。
"""

import asyncio
from pathlib import Path

from nicegui import ui

from core.logging_config import get_logger
from workspaces.screen.overview import get_deepseek_key
from workspaces.screen.knowledge_base import kb_list, kb_lookup, kb_upsert
from workspaces.screen.knowledge_base.sources.douban import parse_apizero
from ui.state import tag
from ui.workspaces.screen._shared import (
    log, clear_log, set_running, set_ready, set_error,
    run_button, build_profile_radio, build_log_panel, mask_key, save_tmdb_key,
)

logger = get_logger(__name__)


def _table_rows(mode: str, profile: str) -> list[dict]:
    """取表格行。豆瓣=只看含豆瓣一手数据的条目并展示豆瓣字段；综合=全部条目最终值。"""
    rows = []
    for e in kb_list(profile):
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
                "seasons": e.get("seasons", ""), "finished": e.get("finished", ""),
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
                ui.label(
                    "从数据库取 from/to/root 全部文件，AI 提取片名后逐条走数据源固化。"
                ).classes("text-sm text-slate-500 font-mono mb-3")

                mode_radio = ui.radio(
                    {"all": "综合（自纠错结果）", "douban": "豆瓣"},
                    value="all",
                ).props("inline").classes("mb-3 text-cyan-300")

                tmdb_key = cfg.get("tmdb_api_key", "")
                with ui.row().classes("gap-2 items-center w-full mb-3"):
                    ui.label("TMDB Key:").classes("text-xs text-slate-500 font-mono w-24")
                    tmdb_input = ui.input(
                        value=mask_key(tmdb_key) if tmdb_key else "",
                        placeholder="未设置（英文名/年份兜底）" if not tmdb_key else "输入新 Key 覆盖",
                    ).props("outlined dense dark").classes("flex-1 font-mono text-xs").on_value_change(
                        lambda e: save_tmdb_key(config_mgr, profile, e.value or "", tmdb_input),
                    )

                run_button(
                    "▶ 更新", "cyan",
                    lambda: _run_update(
                        config_mgr, profile, db, mode_radio.value, _render_table,
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
                    finished_switch = ui.switch("完结").props("color=cyan").classes("ml-2")
                    if profile != "tv":
                        finished_switch.set_visibility(False)
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
            rows = _table_rows(mode_radio.value, profile)
            if not rows:
                ui.label("(知识库为空)").classes("text-xs text-slate-500 font-mono")
                return
            cols = [
                {"name": "zh", "label": "中文名", "field": "zh", "align": "left"},
                {"name": "en", "label": "英文名", "field": "en", "align": "left"},
                {"name": "year", "label": "年份", "field": "year", "align": "left",
                 "style": "white-space: normal; word-break: break-all;"},
                {"name": "score", "label": "豆瓣评分", "field": "score", "align": "left"},
            ]
            if profile == "tv":
                cols.append({"name": "seasons", "label": "季数", "field": "seasons", "align": "left"})
                cols.append({"name": "finished", "label": "完结", "field": "finished", "align": "left"})
            ui.table(columns=cols, rows=rows).classes("w-full")

    def _manual_save():
        """人工补充数据源缺失：直接写入知识库（title 留空，id 由中文名>英文名派生）。"""
        zh = (zh_input.value or "").strip()
        en = (en_input.value or "").strip()
        year = (year_input.value or "").strip()
        score = (score_input.value or "").strip()
        if not zh and not en:
            ui.notify("中文名 / 英文名至少填一个", type="warning")
            return
        kb_upsert(zh, en, year, score, "", profile=profile,
                  finished="完结" if finished_switch.value else "")
        zh_input.value = en_input.value = year_input.value = score_input.value = ""
        finished_switch.value = False
        _render_table()
        ui.notify("已写入知识库", type="positive")

    mode_radio.on_value_change(lambda e: _render_table())
    _render_table()


async def _run_update(config_mgr, profile, db, mode, render_cb):
    """更新知识库：取数据库 from/to/root 文件 → AI 提取中英名 → 去重后逐条 fetch_info 固化。

    mode: "douban" 仅豆瓣源；"all" 仅豆瓣之外的其它源自纠错。
    """
    # 惰性导入：ai_naming 拖 LangChain、sources 拖 chromadb，只在真正更新时才加载
    from workspaces.screen.normalize import extract_names
    from workspaces.screen.knowledge_base.sources import fetch_info, reset_breakers, SEARCH_DELAY, extract_year

    clear_log()
    set_running("更新知识库")
    reset_breakers()

    rows = [
        r for r in await asyncio.to_thread(db.get_media_by_profile, profile)
        if Path(r["mv_path"]).exists()
    ]
    if not rows:
        log("  数据库中无媒体文件（请先到「扫描」同步）", "yellow")
        set_ready()
        return
    # 已固化的（media 表有 zh/en）直接复用，未固化的才走 AI 提取，避免每次重复提取
    files = []
    for r in rows:
        files.append({"name": Path(r["mv_path"]).name, "path": r["mv_path"],
                      "zh": r["zh"] or "", "en": r["en"] or ""})
    pending = [f for f in files if not f["zh"] and not f["en"]]
    log(
        f"  从数据库取到 {len(files)} 个文件（{len(pending)} 个待 AI 提取片名）",
        "gray",
    )

    cfg = config_mgr.get_profile_config(profile)
    key = get_deepseek_key(config_mgr)
    tmdb_key = cfg.get("tmdb_api_key", "")
    log(f"◆ 数据源模式：{'豆瓣' if mode == 'douban' else '综合（豆瓣外源）'}", "cyan")

    if pending:
        if not key:
            log("  未设置 Deepseek Key（请先到「概览」设置）", "red")
            set_error()
            return
        batch = int(cfg.get("ai_batch_size", 20)) or 20
        names = [f["name"] for f in pending]
        extracted: dict[str, dict] = {}
        log("◆ AI 提取文件名中的中英文名 ...", "cyan")
        for i in range(0, len(names), batch):
            chunk = names[i:i + batch]
            try:
                part = await asyncio.to_thread(extract_names, key, chunk, profile == "tv")
            except Exception as e:
                logger.exception("AI 提取失败")
                log(f"  AI 提取失败: {e}", "red")
                set_error()
                return
            extracted.update(part)
        # 固化提取结果到 media 表，下次更新不再重复提取
        for f in pending:
            ext = extracted.get(f["name"]) or {}
            zh = (ext.get("zh") or "").strip()
            en = (ext.get("en") or "").strip()
            if zh or en:
                f["zh"], f["en"] = zh, en
                db.set_media_names(profile, f["path"], zh, en)

    added = skipped = 0
    seen_movie: set[str] = set()  # movie 同批去重（按片名）
    seen_tv: set[str] = set()     # tv 同批去重（数据源返回统一中英名，同名=同剧）
    for f in files:
        name = f["name"]
        zh = (f["zh"] or "").strip()
        en = (f["en"] or "").strip()
        q = zh or en
        if not q:
            log(f"  └ 跳过（未提取到片名）: {name}", "gray")
            skipped += 1
            continue

        # 同批去重；movie 命中缓存即可跳过，tv 逐季更新须每次重查数据源（fetch_info 内不查缓存）
        seen = seen_tv if profile == "tv" else seen_movie
        if q in seen:
            skipped += 1
            log(f"  ⚠ 同批重复片名跳过: {q}", "yellow")
            continue
        if profile != "tv" and kb_lookup(q, profile=profile):
            skipped += 1
            continue
        try:
            info = await asyncio.to_thread(fetch_info, q, tmdb_key, mode, extract_year(name), profile)
        except Exception as e:
            logger.warning("取信息失败 %s: %s", q, e)
            info = None
        if info:
            added += 1
            seen.add(q)
            extra = ""
            if profile == "tv":
                extra = f"/季{info.get('seasons') or '-'}/{info.get('score') or '-'}/{info.get('finished') or '连载'}"
            log(f"  + {q} → {info.get('zh','')}/{info.get('en','')}/{info.get('year','')}{extra}", "green")
        else:
            skipped += 1
            log(f"  └ 未命中数据源: {q}", "gray")
        await asyncio.sleep(SEARCH_DELAY)  # 限流，避免 apizero 429

    log(f"◆ 完成：新增 {added} 条，跳过 {skipped} 条", "cyan")
    render_cb()
    set_ready()

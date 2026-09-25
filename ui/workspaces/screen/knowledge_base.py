"""
知识库模块（screen）— chromadb 映射浏览 + AI 扩充 + 豆瓣修正。

展示：表格列出 chromadb 中「中文名/英文名/年份/豆瓣评分」（电视剧加季数/完结）。
扩充：点「更新」，从数据库取 from/to/root 全部媒体文件，AI 提取中英文名后逐条走
      豆瓣外源（TMDB/时光网/维基）固化；点「豆瓣修正」，用已有中英文名回豆瓣补评分等字段。
"""

import asyncio
import urllib.error
from pathlib import Path

from nicegui import ui

from core.logging_config import get_logger
from workspaces.screen.overview import get_deepseek_key
from workspaces.screen.knowledge_base import kb_list, kb_lookup, kb_upsert, kb_delete
from ui.state import tag
from ui.workspaces.screen._shared import (
    set_running, set_ready, set_error,
    run_button, build_profile_radio, build_log_panel, mask_key, save_tmdb_key, save_tvdb_key,
    make_page_logger,
)

log, clear_log = make_page_logger("kb")

logger = get_logger(__name__)


def _save_row(cid, title, raw, zh_i, en_i, year_i, score_i, seasons_i, finished_i, profile, episodes=None, subtitle_status=""):
    """编辑保存：按稳定 id 删旧写新，避免改中英文名导致 id 漂移产生孤儿条目。

    episodes/subtitle_status 为派生的副标题信息，编辑其余字段时原样带回，避免被清空。
    """
    zh = (zh_i.value or "").strip()
    en = (en_i.value or "").strip()
    if not zh and not en:
        ui.notify("中文名 / 英文名至少填一个", type="warning")
        return
    kb_delete(cid, profile=profile)
    kb_upsert(zh, en, (year_i.value or "").strip(), (score_i.value or "").strip(),
              title, raw, profile=profile,
              seasons=(seasons_i.value or "").strip() if seasons_i else "",
              finished=(finished_i.value or "").strip() if finished_i else "",
              episodes=episodes, subtitle_status=subtitle_status)
    log(f"  ✓ 已修改: {zh or en}", "green")
    kb_table.refresh(profile)


def _delete_row(cid, name, profile):
    """手动删除：按稳定 id 从知识库移除并刷新表格。"""
    kb_delete(cid, profile=profile)
    log(f"  ✕ 已删除: {name}", "red")
    kb_table.refresh(profile)


@ui.refreshable
def kb_table(profile):
    """从 chromadb（知识库的单一数据源）渲染映射表。"""
    rows = kb_list(profile)
    if not rows:
        ui.label("(知识库为空)").classes("text-xs text-slate-500 font-mono")
        return
    headers = [("中文名", "flex-1"), ("英文名", "flex-1"),
               ("年份", "flex-1"), ("豆瓣评分", "flex-1")]
    if profile == "tv":
        headers += [("季数", "w-16"), ("完结", "w-20"), ("副标题", "w-16")]
    with ui.row().classes("w-full gap-1 items-center mb-1"):
        for label, w in headers:
            ui.label(label).classes(f"{w} min-w-0 text-xs text-slate-500 font-mono")
        ui.label("").classes("w-16")
    for e in rows:
        cid = e["_id"]
        title = e.get("title", "")
        raw = e.get("raw") or {}
        episodes = e.get("episodes")
        subtitle_status = e.get("subtitle_status", "")
        with ui.row().classes("w-full gap-1 items-center mb-1"):
            zh_i = ui.input(value=e.get("zh", "")).classes(
                "flex-1 min-w-0 font-mono text-xs").props("outlined dense dark")
            en_i = ui.input(value=e.get("en", "")).classes(
                "flex-1 min-w-0 font-mono text-xs").props("outlined dense dark")
            year_i = ui.input(value=e.get("year", "")).classes(
                "flex-1 min-w-0 font-mono text-xs").props("outlined dense dark")
            score_i = ui.input(value=e.get("score", "")).classes(
                "flex-1 min-w-0 font-mono text-xs").props("outlined dense dark")
            seasons_i = finished_i = None
            if profile == "tv":
                seasons_i = ui.input(value=e.get("seasons", "")).classes(
                    "w-16 font-mono text-xs").props("outlined dense dark")
                finished_i = ui.input(value=e.get("finished", "")).classes(
                    "w-20 font-mono text-xs").props("outlined dense dark")
                # 副标题有无为派生展示（由 episodes 判定），不可手改，用只读 label
                ui.label(subtitle_status or "无").classes(
                    "w-16 font-mono text-xs text-slate-300")
            # 默认参数逐个绑定循环变量，避免闭包晚绑定导致所有行按钮都作用于最后一行
            with ui.row().classes("gap-0 items-center w-16"):
                ui.button("✔", on_click=lambda cid=cid, title=title, raw=raw,
                          zh_i=zh_i, en_i=en_i, year_i=year_i, score_i=score_i,
                          seasons_i=seasons_i, finished_i=finished_i, profile=profile,
                          episodes=episodes, subtitle_status=subtitle_status:
                          _save_row(cid, title, raw, zh_i, en_i, year_i, score_i,
                                    seasons_i, finished_i, profile, episodes, subtitle_status)).props(
                    "dense flat color=cyan").classes("w-8")
                ui.button("✕", on_click=lambda cid=cid,
                          name=(e.get("zh") or e.get("en")), profile=profile:
                          _delete_row(cid, name, profile)).props(
                    "dense flat color=red").classes("w-8")


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

                tmdb_key = cfg.get("tmdb_api_key", "")
                with ui.row().classes("gap-2 items-center w-full mb-2"):
                    ui.label("TMDB Key:").classes("text-xs text-slate-500 font-mono w-24")
                    tmdb_input = ui.input(
                        value=mask_key(tmdb_key) if tmdb_key else "",
                        placeholder="未设置（英文名/年份兜底）" if not tmdb_key else "输入新 Key 覆盖",
                    ).props("outlined dense dark").classes("flex-1 font-mono text-xs").on_value_change(
                        lambda e: save_tmdb_key(config_mgr, profile, e.value or "", tmdb_input),
                    )
                if profile == "tv":
                    tvdb_key = cfg.get("tvdb_api_key", "")
                    with ui.row().classes("gap-2 items-center w-full mb-3"):
                        ui.label("TVDB Key:").classes("text-xs text-slate-500 font-mono w-24")
                        tvdb_input = ui.input(
                            value=mask_key(tvdb_key) if tvdb_key else "",
                            placeholder="未设置（电视剧中文名/季数兜底）" if not tvdb_key else "输入新 Key 覆盖",
                        ).props("outlined dense dark").classes("flex-1 font-mono text-xs").on_value_change(
                            lambda e: save_tvdb_key(config_mgr, profile, e.value or "", tvdb_input),
                        )

                with ui.row().classes("gap-2"):
                    run_button(
                        "▶ 更新", "cyan",
                        lambda: _run_update(config_mgr, profile, db),
                    )
                    run_button(
                        "▶ 豆瓣修正", "green",
                        lambda: _run_douban_fix(profile),
                    )

            with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-6 w-full mb-6"):
                tag("kb-manual")
                ui.label("◆ 人工更新").classes("text-lg font-mono text-cyan-400 mb-2")
                with ui.row().classes("gap-2 items-center w-full"):
                    zh_input = ui.input(placeholder="中文名").classes(
                        "flex-1 min-w-0 font-mono text-xs").props("outlined dense dark")
                    en_input = ui.input(placeholder="英文名").classes(
                        "flex-1 min-w-0 font-mono text-xs").props("outlined dense dark")
                    year_input = ui.input(placeholder="年份").classes(
                        "flex-1 min-w-0 font-mono text-xs").props("outlined dense dark")
                    score_input = ui.input(placeholder="豆瓣评分(可空)").classes(
                        "flex-1 min-w-0 font-mono text-xs").props("outlined dense dark")
                    seasons_input = ui.input(placeholder="季数").classes(
                        "w-20 font-mono text-xs").props("outlined dense dark")
                    finished_switch = ui.switch("完结").props("color=cyan").classes("ml-2")
                    if profile != "tv":
                        seasons_input.set_visibility(False)
                        finished_switch.set_visibility(False)
                    ui.button("✔ 保存", on_click=lambda: _manual_save()).classes(
                        "bg-cyan-900 hover:bg-cyan-700 text-cyan-300 font-mono text-sm "
                        "border border-cyan-600 rounded px-4 py-1"
                    )

            with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-6 w-full"):
                tag("kb-table")
                ui.label("◆ 映射表").classes("text-lg font-mono text-cyan-400 mb-2")
                kb_table(profile)

        build_log_panel("kb")

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
                  seasons=(seasons_input.value or "").strip(),
                  finished="完结" if finished_switch.value else "")
        zh_input.value = en_input.value = year_input.value = score_input.value = ""
        seasons_input.value = ""
        finished_switch.value = False
        kb_table.refresh(profile)
        ui.notify("已写入知识库", type="positive")


async def _run_update(config_mgr, profile, db):
    """更新知识库：取数据库 from/to/root 文件 → AI 提取中英名 → 去重后逐条走豆瓣外源自纠错固化。"""
    # 惰性导入：ai_naming 拖 LangChain、sources 拖 chromadb，只在真正更新时才加载
    from workspaces.screen.normalize import extract_names
    from workspaces.screen.knowledge_base.sources import (
        fetch_info, reset_breakers, SEARCH_DELAY, extract_year, last_miss_reason,
    )

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
    tvdb_key = cfg.get("tvdb_api_key", "")
    log("◆ 数据源：综合（豆瓣外源自纠错）", "cyan")

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
        miss = ""
        try:
            info = await asyncio.to_thread(fetch_info, q, tmdb_key, "all", extract_year(name), profile, tvdb_key)
        except Exception as e:
            logger.warning("取信息失败 %s: %s", q, e)
            info = None
            miss = f"异常: {e}"
        else:
            if not info:
                miss = last_miss_reason()
        if info:
            added += 1
            seen.add(q)
            extra = ""
            if profile == "tv":
                extra = f"/季{info.get('seasons') or '-'}/{info.get('score') or '-'}/{info.get('finished') or '连载'}"
            log(f"  + {q} → {info.get('zh','')}/{info.get('en','')}/{info.get('year','')}{extra}", "green")
        else:
            skipped += 1
            log(f"  └ 未命中数据源: {q}" + (f"（{miss}）" if miss else ""), "gray")
        await asyncio.sleep(SEARCH_DELAY)  # 限流，避免 apizero 429

    log(f"◆ 完成：新增 {added} 条，跳过 {skipped} 条", "cyan")
    kb_table.refresh(profile)
    set_ready()


def _douban_wait(exc) -> str:
    """从 429 响应提取还需等待的时长文案（Retry-After 秒数，无则默认 60 秒）。"""
    secs = 60
    headers = getattr(exc, "headers", None) or {}
    try:
        secs = int(headers.get("Retry-After", secs))
    except (TypeError, ValueError):
        secs = 60
    return f"{secs} 秒" if secs < 60 else f"{secs // 60} 分钟"


async def _run_douban_fix(profile):
    """豆瓣修正：对知识库中无豆瓣评分的条目，用已有中英文名回豆瓣补字段（豆瓣数据优先）。

    英文名优先作查询词；中英文名沿用已有，其余字段（评分/年份/季数/是否完结）以豆瓣为准，
    豆瓣缺失才保留已有。豆瓣 429 达访问上限即停止，红字提示剩余等待时间。
    """
    from workspaces.screen.knowledge_base.sources import SEARCH_DELAY
    from workspaces.screen.knowledge_base.sources.douban import fetch_douban, fetch_douban_tv

    clear_log()
    set_running("豆瓣修正")

    rows = kb_list(profile)
    pending = [r for r in rows if not (r.get("score") or "").strip()]
    if not pending:
        log("  无待修正条目（均有豆瓣评分）", "gray")
        set_ready()
        return
    log(f"  待修正 {len(pending)} 条（无豆瓣评分），英文名优先回豆瓣", "gray")

    fixed = skipped = 0
    for r in pending:
        q = (r.get("en") or r.get("zh") or "").strip()
        if not q:
            skipped += 1
            continue
        try:
            info = fetch_douban_tv(q) if profile == "tv" else fetch_douban(q)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                log(f"  ✕ 豆瓣访问达上限，约 {_douban_wait(e)} 后可继续", "red")
                break
            info = None
        except Exception:
            info = None
        if not info:
            skipped += 1
            continue
        raw = dict(r.get("raw") or {})
        if info.get("raw"):
            raw["douban"] = info["raw"]
        kb_upsert(
            r.get("zh", ""), r.get("en", ""),
            info.get("year") or r.get("year", ""),
            info.get("score") or "",
            r.get("title", ""), raw, profile=profile,
            seasons=info.get("seasons") or r.get("seasons", ""),
            finished=info.get("finished") or r.get("finished", ""),
            episodes=r.get("episodes"), subtitle_status=r.get("subtitle_status", ""),
        )
        fixed += 1
        log(f"  ✓ {q} → 评分[{info.get('score') or '-'}]/年份[{info.get('year') or '-'}]", "green")
        await asyncio.sleep(SEARCH_DELAY)

    log(f"◆ 完成：修正 {fixed} 条，跳过 {skipped} 条", "cyan")
    kb_table.refresh(profile)
    set_ready()

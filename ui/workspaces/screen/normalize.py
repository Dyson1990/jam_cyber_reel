"""
标准化模块（screen）— 文件名规范化 + 重命名。

命名方式单选：
    - 映射命名：dict 映射 str.replace
    - AI 命名：deepseek 生成映射（from → to）
    - AI 修正：检查 root 中已检查文件的可查询槽位（原地改名）

源文件不再自行扫盘：from / root 文件由「扫描」写入数据库（含来源），
本页直接按来源从数据库取文件路径；To 仍为通用参数（config.py）。
"""

import asyncio
import json

from datetime import datetime
from pathlib import Path

from nicegui import ui

from core.files import move_to_structure, rollback_structure, scan_videos
from core.logging_config import get_log_dir, get_logger
from workspaces._shared import parse_naming_rules
from workspaces.screen.normalize import (
    build_prompt, build_tv_prompt, build_fix_prompt, call_deepseek, tv_summarizable,
)
from workspaces.screen.overview import get_deepseek_key
from workspaces.screen.knowledge_base.sources import fetch_infos
from workspaces.screen.knowledge_base import kb_lookup
from workspaces.screen.scan import media_files, resync_db
from ui.state import tag, update_drawer_info, cancel_requested
from ui.workspaces.screen._shared import (
    log, clear_log, set_running, set_ready, set_error,
    run_button, build_profile_radio, build_log_panel, mask_key, save_tmdb_key,
)

logger = get_logger(__name__)


def build_normalize(config_mgr, db, registry):
    """构建标准化页 UI。"""
    profile = config_mgr.current_profile
    handler = registry.get(profile)
    cfg = config_mgr.get_profile_config()
    naming_mode = cfg.get("naming_mode", "mapping")

    tag("normalize")
    ui.label("◆ 标准化").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")
    build_profile_radio(config_mgr, "normalize")

    if not handler:
        ui.label("⚠ 当前 Profile 未加载 handler").classes("text-red-400 font-mono")
        return

    with ui.row().classes("w-full").style("position: relative;"):
        with ui.column().classes("flex-1 min-w-0").style("margin-right: calc(38% + 1rem);"):
            with ui.card().classes(
                "bg-slate-950 border border-cyan-800 rounded-lg p-6 w-full mb-6"
            ):
                tag("normalize-config")
                ui.label("◆ 文件名更新").classes("text-lg font-mono text-cyan-400 mb-2")

                # 命名方式单选：映射命名 / AI 命名 / AI 修正
                method_radio = ui.radio(
                    {"mapping": "映射命名", "ai": "AI 命名", "ai_fix": "AI 修正"},
                    value=naming_mode,
                    on_change=lambda e: _on_method_change(
                        config_mgr, profile, e.value, _render,
                    ),
                ).props("inline").classes("mb-3 text-cyan-300")

                top_container = ui.column().classes("w-full")
                sub_container = ui.column().classes("w-full")

                def _render():
                    top_container.clear()
                    sub_container.clear()
                    with top_container:
                        if method_radio.value != "ai_fix":
                            _build_to_row(config_mgr, profile)
                    with sub_container:
                        if method_radio.value == "ai":
                            _build_ai_naming(config_mgr, profile, handler, db)
                        elif method_radio.value == "ai_fix":
                            _build_ai_fix(config_mgr, profile, handler, db)
                        else:
                            _build_mapping_naming(handler, config_mgr, profile, db)

                _render()

        build_log_panel()


def _on_method_change(config_mgr, profile, value, render):
    config_mgr.update_profile_config(profile, "naming_mode", value)
    render()


def _build_to_row(config_mgr, profile):
    """标准化后的目标目录 To（输入即保存；from 源文件由数据库提供）。"""
    cfg = config_mgr.get_profile_config(profile)
    with ui.row().classes("gap-2 items-center w-full mb-4"):
        ui.label("To:").classes("text-xs text-slate-500 font-mono w-20")
        ui.input(value=cfg.get("to", ""), placeholder="D:/Media/To").classes(
            "flex-1 font-mono text-xs"
        ).props("outlined dense dark").on_value_change(
            lambda e: config_mgr.update_profile_config(profile, "to", e.value or ""),
        )


def _build_rollback_row(handler, source_key="from"):
    """回滚按钮行：回滚上一批 + 批量回滚（含日期范围）排在一行。

    source_key 指定回滚目标目录的配置键（映射/AI 命名用 "from"，AI 修正用 "root"）。
    """
    with ui.row().classes("gap-2 items-center mt-3"):
        run_button(
            "↺ 回滚上一批", "cyan", lambda: _run_rollback_batch(handler, source_key),
            pad="px-4 py-2",
        )
        ui.label("日期范围：").classes("text-xs text-slate-500 font-mono")
        date_from = ui.input(value="", placeholder="YYYY-MM-DD").classes(
            "w-36 font-mono text-xs"
        ).props("outlined dense dark type=date")
        date_to = ui.input(value="", placeholder="YYYY-MM-DD").classes(
            "w-36 font-mono text-xs"
        ).props("outlined dense dark type=date")
        run_button(
            "↺↺ 批量回滚", "cyan",
            lambda: _run_rollback_range(handler, date_from, date_to, source_key),
            pad="px-4 py-2",
        )


def _build_mapping_naming(handler, config_mgr, profile, db):
    """映射命名页面：命名规则 + 文件名更新 / 回滚。"""
    cfg = config_mgr.get_profile_config(profile)
    rules_str = json.dumps(cfg.get("naming_rules", {}), ensure_ascii=False, indent=2)

    tag("naming-mapping")
    ui.label("命名规则 (Naming Rules):").classes("text-xs text-slate-500 font-mono mb-1")
    ui.textarea(value=rules_str).classes(
        "w-full bg-slate-700 text-cyan-100 font-mono text-sm"
    ).style("min-height: 100px;").on_value_change(
        lambda e: _save_rules(config_mgr, profile, e.value),
    )

    with ui.row().classes("gap-4 mt-4"):
        run_button("▶ 文件名更新", "cyan", lambda: _run_rename(handler, db))

    _build_rollback_row(handler)


def _build_ai_naming(config_mgr, profile, handler, db):
    """AI 命名页面：TMDB key（脱敏显示）+ 提示词 + 生成/预览/应用三按钮。"""
    cfg = config_mgr.get_profile_config(profile)

    tag("naming-ai")
    ui.label("AI 命名").classes("text-xs text-cyan-500 font-mono mb-2")

    tmdb_key = cfg.get("tmdb_api_key", "")
    with ui.row().classes("gap-2 items-center w-full mb-3"):
        ui.label("TMDB Key:").classes("text-xs text-slate-500 font-mono w-24")
        tmdb_input = ui.input(
            value=mask_key(tmdb_key) if tmdb_key else "",
            placeholder="未设置（免费 Key，英文名/年份兜底）" if not tmdb_key else "输入新 Key 覆盖",
        ).props("outlined dense dark").classes("flex-1 font-mono text-xs").on_value_change(
            lambda e: save_tmdb_key(config_mgr, profile, e.value or "", tmdb_input),
        )

    with ui.row().classes("gap-2 items-center w-full mb-3"):
        ui.label("每次季数:" if profile == "tv" else "每次文件名数:").classes(
            "text-xs text-slate-500 font-mono w-24"
        )
        ui.number(
            value=cfg.get("ai_batch_size", 20), min=1, max=500, step=1,
        ).props("outlined dense dark").classes("w-24 font-mono text-xs").on_value_change(
            lambda e: config_mgr.update_profile_config(
                profile, "ai_batch_size", int(e.value or 20),
            ),
        )

    with ui.row().classes("gap-2 items-center w-full mb-3"):
        ui.label("豆瓣评分/年份:").classes("text-xs text-slate-500 font-mono w-24")
        ui.switch(value=bool(cfg.get("ai_douban", False))).props(
            "dense color=cyan"
        ).on_value_change(
            lambda e: config_mgr.update_profile_config(
                profile, "ai_douban", bool(e.value),
            ),
        )

    with ui.row().classes("gap-2 items-center w-full mb-1"):
        ui.label("提示词 (Prompt):").classes("text-xs text-slate-500 font-mono")
        _updated = cfg.get("ai_prompt_updated", "")
        ui.label(
            f"更新于 {_updated}" if _updated else "尚未生成"
        ).classes("text-xs text-slate-600 font-mono")
    prompt_area = ui.textarea(value=cfg.get("ai_prompt", "")).classes(
        "w-full bg-slate-700 text-cyan-100 font-mono text-sm"
    ).style("min-height: 100px;").on_value_change(
        lambda e: config_mgr.update_profile_config(
            profile, "ai_prompt", e.value or "",
        ),
    )

    result_state = {"result": {}}

    with ui.row().classes("gap-3 mt-4"):
        run_button("生成需求", "cyan", lambda: _gen_prompt(config_mgr, profile, db, prompt_area))
        run_button("预览改动", "cyan", lambda: _preview(config_mgr, profile, prompt_area, result_state, result_container))
        run_button("应用映射", "cyan", lambda: _apply(config_mgr, profile, handler, result_state))

    _build_rollback_row(handler)

    result_container = ui.column().classes("w-full mt-4")


def _build_ai_fix(config_mgr, profile, handler, db):
    """AI 修正页面：检查 root 中已检查文件的可查询补充槽位（中文名/英文名/年份/评分）。"""
    cfg = config_mgr.get_profile_config(profile)

    tag("naming-ai-fix")
    ui.label("AI 修正").classes("text-xs text-cyan-500 font-mono mb-2")

    with ui.row().classes("gap-2 items-center w-full mb-1"):
        ui.label("提示词 (Prompt):").classes("text-xs text-slate-500 font-mono")
        _updated = cfg.get("ai_prompt_updated", "")
        ui.label(
            f"更新于 {_updated}" if _updated else "尚未生成"
        ).classes("text-xs text-slate-600 font-mono")
    prompt_area = ui.textarea(value=cfg.get("ai_prompt", "")).classes(
        "w-full bg-slate-700 text-cyan-100 font-mono text-sm"
    ).style("min-height: 100px;").on_value_change(
        lambda e: config_mgr.update_profile_config(profile, "ai_prompt", e.value or ""),
    )

    result_state = {"result": {}, "selected": {}}

    with ui.row().classes("gap-3 mt-4"):
        run_button("生成需求", "cyan", lambda: _gen_fix_prompt(config_mgr, profile, db, prompt_area))
        run_button("预览改动", "cyan", lambda: _preview_fix(config_mgr, profile, prompt_area, result_state, result_container))
        run_button("应用映射", "cyan", lambda: _apply_fix(config_mgr, profile, handler, result_state))

    _build_rollback_row(handler, source_key="root")

    result_container = ui.column().classes("w-full mt-4")


def _save_rules(config_mgr, profile, value):
    try:
        rules = parse_naming_rules(value)
    except json.JSONDecodeError:
        return  # 忽略无效 JSON，待输入完整
    config_mgr.update_profile_config(profile, "naming_rules", rules)


# ==================== AI 命名三步 ====================

async def _gen_prompt(config_mgr, profile, db, prompt_area):
    """生成需求：取数据库中来源为 from 的文件（tv=系列文件夹内集文件），组装提示词。"""
    clear_log()
    set_running("生成需求")
    rows = [
        r for r in await asyncio.to_thread(db.get_media_by_profile, profile)
        if r["source"] == "from" and Path(r["mv_path"]).exists()
    ]
    files = [Path(r["mv_path"]) for r in rows]
    if not files:
        log("  数据库中无来源为 from 的文件（请先到「扫描」同步）", "yellow")
        set_ready()
        return
    cfg = config_mgr.get_profile_config(profile)
    tmdb_key = cfg.get("tmdb_api_key", "")
    tvdb_key = cfg.get("tvdb_api_key", "")
    if profile == "tv":
        # 电视剧：以季（系列文件夹）为单位分批，中英文名/逐季年份优先复用知识库
        limit = cfg.get("ai_batch_size", 20) or 0
        episodes: list[str] = []
        series: dict[str, Path] = {}  # folder.name → Path，空文件夹（已处理完）直接跳过
        for folder in files:
            vfs = await asyncio.to_thread(scan_videos, folder)
            if not vfs:
                continue  # 已处理完/空文件夹：不占「每次季数」名额，也不进「查询结果」
            series[folder.name] = folder
            for vf in vfs:
                # 保留系列文件夹内的相对子路径（可能已有季子目录），否则 vf.name
                # 会丢掉季目录、生成扁平 old 路径，应用映射时找不到源文件（WinError 2）
                episodes.append(f"{folder.name}/{vf.relative_to(folder).as_posix()}")
        if not episodes:
            log("  各系列文件夹内无视频文件", "yellow")
            set_ready()
            return
        # 「每次季数」按「待标准化集文件」里实际列出的系列计：无法总结的先剔除，不占名额
        order, unsum = tv_summarizable(episodes)
        for name in unsum:
            log(f"  ⚠ 「{name}」各集名称差距过大无法总结，已跳过（请手动处理）", "yellow")
        keep = order[:limit] if limit else order
        keep_set = set(keep)
        episodes = [ep for ep in episodes if ep.partition("/")[0] in keep_set]
        # 知识库优先：media 表已固化 AI 提取的中英文名，命中 chromadb 直接复用，缺失才走网络
        clean = {
            Path(r["mv_path"]): (r["zh"] or "").strip() or (r["en"] or "").strip()
            for r in rows
        }
        infos: dict[str, dict] = {}
        miss: list[str] = []
        for name in keep:
            q = clean.get(series[name])
            hit = kb_lookup(q, profile="tv") if q else None
            if hit:
                infos[name] = hit
            else:
                miss.append(name)
        if miss:
            net = await asyncio.to_thread(fetch_infos, miss, tmdb_key, profile, tvdb_key)
            infos.update(net)
        prompt, _ = build_tv_prompt(episodes, infos)
        if not prompt:
            log("  本批集文件全部无法总结，未生成提示词", "red")
            set_ready()
            return
        msg = f"  已生成提示词：共 {len(episodes)} 个集文件，{len(keep)} 个季"
        if infos:
            msg += f"，命中 {len(infos)} 个系列"
    else:
        limit = cfg.get("ai_batch_size", 20)
        names = [f.name for f in files]
        batch = names[:limit] if limit else names
        infos = {}
        if cfg.get("ai_douban", False):
            infos = await asyncio.to_thread(
                fetch_infos, batch, tmdb_key, profile, tvdb_key,
            )
        prompt = build_prompt(batch, limit=limit, infos=infos, is_tv=False)
        msg = f"  已生成提示词：共 {len(names)} 个文件，取前 {len(batch)} 个"
        if infos:
            msg += f"，命中 {len(infos)} 条"
    if not prompt_area.is_deleted:
        prompt_area.set_value(prompt)
    config_mgr.update_profile_config(profile, "ai_prompt", prompt)
    config_mgr.update_profile_config(
        profile, "ai_prompt_updated", datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    log(msg, "cyan")
    set_ready()


async def _preview(config_mgr, profile, prompt_area, result_state, result_container):
    """预览改动：提交提示词框内容（人工修改后）给 deepseek，表格展示映射。"""
    key = get_deepseek_key(config_mgr)
    prompt = (prompt_area.value or "").strip()
    if not key:
        log("  未设置 Deepseek Key", "red")
        set_error()
        return
    if not prompt:
        log("  提示词为空，请先点「生成需求」", "red")
        set_error()
        return
    clear_log()
    set_running("预览改动")
    log("◆ 正在调用 Deepseek ...", "cyan")
    try:
        result, errors = await asyncio.to_thread(call_deepseek, key, prompt)
    except Exception as e:
        logger.exception("deepseek 调用失败")
        log(f"  调用失败: {e}", "red")
        set_error()
        return
    result_state["result"] = result
    _save_mapping(result)
    _render_result_table(result_container, result, profile)
    if errors:
        log(f"  跳过 {len(errors)} 条（必填槽位缺失）:", "yellow")
        for e in errors:
            log(f"    └ {e.get('file','?')}: {e.get('reason','?')}", "yellow")
    log(f"  返回 {len(result)} 条映射，已显示表格", "green")
    set_ready()


async def _apply(config_mgr, profile, handler, result_state):
    """应用映射：按预览结果重命名（从 from 移动到 to）。"""
    clear_log()
    set_running("应用映射")
    result = result_state.get("result", {})
    if not result:
        log("  尚无预览结果，请先点「预览改动」", "red")
        set_error()
        return
    cfg = config_mgr.get_profile_config(profile)
    from_path = cfg.get("from", "")
    to_path = cfg.get("to", "")
    if not from_path:
        log("  From 未设置", "red")
        set_error()
        return
    if not to_path:
        log("  To 未设置", "red")
        set_error()
        return
    from_dir = Path(from_path)
    to_dir = Path(to_path)
    mapping = {from_dir / old: new for old, new in result.items() if old != new}
    if not mapping:
        log("  所有文件名已符合规范，无需更名", "yellow")
        set_ready()
        return
    try:
        if profile == "tv":
            records = await asyncio.to_thread(
                move_to_structure, mapping, to_dir, from_dir, handler.db, profile,
            )
        else:
            records = await asyncio.to_thread(handler.rename, mapping, target_dir=to_dir)
    except Exception as e:
        logger.exception("AI 重命名失败 profile=%s", profile)
        log(f"  重命名失败: {e}", "red")
        set_error()
        return
    ok = sum(1 for r in records if r.get("status") == "成功")
    fail = len(records) - ok
    log(
        f"  rename: {ok} 成功, {fail} 失败（移动到 {to_dir}）",
        "green" if fail == 0 else "yellow",
    )
    for r in records:
        if r.get("status") != "成功":
            log(
                f"    └ {r.get('old_name','?')} → {r.get('new_name','?')}: "
                f"{r.get('status')}",
                "red",
            )
    try:
        net = await asyncio.to_thread(resync_db, cfg, handler.db, profile)
        log(f"  db 同步: 新增-删除净变化 {net:+d}", "gray")
    except Exception as e:
        logger.exception("重命名后同步 media 表失败")
        log(f"  db 同步失败: {e}", "yellow")
    update_drawer_info()
    set_ready()


def _save_mapping(result: dict[str, str]) -> None:
    """把 Deepseek 返回的映射落盘到 logs/screen/ai_mapping.json（覆盖写，只留最新）。"""
    log_dir = get_log_dir()
    if not log_dir:
        return
    screen_dir = log_dir / "screen"
    screen_dir.mkdir(parents=True, exist_ok=True)
    path = screen_dir / "ai_mapping.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  映射已保存: logs/screen/{path.name}", "gray")


def _render_result_table(container, result, profile="movie"):
    """在容器内渲染映射表格：原文件名 → 新文件名（电视剧三级路径按 / 拆行展示）。"""
    if container.is_deleted:
        return
    container.clear()
    with container:
        if not result:
            ui.label("(无结果)").classes("text-xs text-slate-500 font-mono")
            return
        if profile == "tv":
            _render_tv_mapping(container, result)
            return
        rows = [{"old": k, "new": v} for k, v in result.items()]
        ui.table(
            columns=[
                {"name": "old", "label": "原文件名", "field": "old", "align": "left"},
                {"name": "new", "label": "新文件名", "field": "new", "align": "left"},
            ],
            rows=rows,
        ).classes("w-full")


def _render_tv_mapping(container, result):
    """电视剧映射表：old=系列/集、new=系列/季/集 均较长，逐段换行显示，避免单行溢出。"""
    with ui.row().classes("gap-2 items-center w-full text-xs text-slate-400 font-mono mb-1"):
        ui.label("原相对路径").classes("flex-1")
        ui.label("新相对路径").classes("flex-1")
    for old, new in result.items():
        with ui.row().classes("gap-2 items-start w-full border-b border-slate-800 py-1"):
            with ui.column().classes("flex-1 min-w-0 gap-0"):
                for seg in old.split("/"):
                    ui.label(seg).classes("text-xs font-mono text-slate-300 break-all")
            with ui.column().classes("flex-1 min-w-0 gap-0"):
                for seg in new.split("/"):
                    ui.label(seg).classes("text-xs font-mono text-cyan-300 break-all")


# ==================== AI 修正三步 ====================

async def _gen_fix_prompt(config_mgr, profile, db, prompt_area):
    """生成修正需求：取数据库中来源为 root 的文件，取豆瓣信息，组装修正提示词。"""
    clear_log()
    set_running("生成修正需求")
    files = [
        f for f in await asyncio.to_thread(media_files, db, profile, "root")
        if f.exists()
    ]
    if not files:
        log("  数据库中无来源为 root 的文件（请先到「扫描」同步）", "yellow")
        set_ready()
        return
    names = [f.name for f in files]
    infos = await asyncio.to_thread(
        fetch_infos, names,
        config_mgr.get_profile_config(profile).get("tmdb_api_key", ""),
        profile,
        config_mgr.get_profile_config(profile).get("tvdb_api_key", ""),
    )
    prompt = build_fix_prompt(names, infos=infos, is_tv=profile == "tv")
    if not prompt_area.is_deleted:
        prompt_area.set_value(prompt)
    config_mgr.update_profile_config(profile, "ai_prompt", prompt)
    config_mgr.update_profile_config(
        profile, "ai_prompt_updated", datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    msg = f"  已生成修正提示词：共 {len(names)} 个文件"
    if infos:
        msg += f"，命中 {len(infos)} 条"
    log(msg, "cyan")
    set_ready()


async def _preview_fix(config_mgr, profile, prompt_area, result_state, result_container):
    """预览修正：提交提示词给 deepseek，表格展示（含勾选框）。"""
    key = get_deepseek_key(config_mgr)
    prompt = (prompt_area.value or "").strip()
    if not key:
        log("  未设置 Deepseek Key", "red")
        set_error()
        return
    if not prompt:
        log("  提示词为空，请先点「生成需求」", "red")
        set_error()
        return
    clear_log()
    set_running("预览改动")
    log("◆ 正在调用 Deepseek ...", "cyan")
    try:
        result, errors = await asyncio.to_thread(call_deepseek, key, prompt)
    except Exception as e:
        logger.exception("deepseek 调用失败")
        log(f"  调用失败: {e}", "red")
        set_error()
        return
    result_state["result"] = result
    result_state["selected"] = {k: True for k in result}
    _save_mapping(result)
    _render_fix_table(result_container, result, result_state["selected"])
    if errors:
        log(f"  跳过 {len(errors)} 条（必填槽位缺失）:", "yellow")
        for e in errors:
            log(f"    └ {e.get('file','?')}: {e.get('reason','?')}", "yellow")
    log(f"  返回 {len(result)} 条映射，已显示表格", "green")
    set_ready()


async def _apply_fix(config_mgr, profile, handler, result_state):
    """应用修正：仅重命名勾选的条目（原地改名，root 目录内）。"""
    clear_log()
    set_running("应用修正")
    result = result_state.get("result", {})
    selected = result_state.get("selected", {})
    if not result:
        log("  尚无预览结果，请先点「预览改动」", "red")
        set_error()
        return
    path = config_mgr.get_profile_config(profile).get("root", "")
    if not path:
        log("  Root 未设置", "red")
        set_error()
        return
    path_dir = Path(path)
    mapping = {
        path_dir / old: new
        for old, new in result.items()
        if old != new and selected.get(old, False)
    }
    if not mapping:
        log("  未勾选任何需更名的条目", "yellow")
        set_ready()
        return
    try:
        records = await asyncio.to_thread(handler.rename, mapping)
    except Exception as e:
        logger.exception("AI 修正重命名失败 profile=%s", profile)
        log(f"  重命名失败: {e}", "red")
        set_error()
        return
    ok = sum(1 for r in records if r.get("status") == "成功")
    fail = len(records) - ok
    log(f"  rename: {ok} 成功, {fail} 失败（原地改名）", "green" if fail == 0 else "yellow")
    for r in records:
        if r.get("status") != "成功":
            log(f"    └ {r.get('old_name','?')} → {r.get('new_name','?')}: {r.get('status')}", "red")
    update_drawer_info()
    set_ready()


def _render_fix_table(container, result, selected):
    """渲染修正映射表格：勾选框 + 原文件名 → 新文件名。"""
    if container.is_deleted:
        return
    container.clear()
    with container:
        if not result:
            ui.label("(无结果)").classes("text-xs text-slate-500 font-mono")
            return
        with ui.row().classes("gap-2 items-center w-full text-xs text-slate-400 font-mono mb-1"):
            ui.label("勾选").classes("w-10")
            ui.label("原文件名").classes("flex-1")
            ui.label("新文件名").classes("flex-1")
        for old, new in result.items():
            def _toggle(e, k=old):
                selected[k] = bool(e.value)
            with ui.row().classes("gap-2 items-center w-full"):
                ui.checkbox(value=selected.get(old, True)).props(
                    "dense color=cyan"
                ).on_value_change(_toggle)
                ui.label(old).classes("flex-1 text-xs font-mono text-slate-300")
                ui.label(new).classes("flex-1 text-xs font-mono text-cyan-300")


# ==================== 文件名更新逻辑 ====================

async def _run_rename(handler, db):
    """执行文件名更新：取数据库 from 文件 → normalize → rename（移动到 to）。"""
    clear_log()
    set_running("文件名更新")
    log("◆ 开始文件名更新...", "cyan")

    cfg = handler.config
    to_path = cfg.get("to", "")
    if not to_path:
        log("  To 未设置", "red")
        set_error()
        return

    to_dir = Path(to_path)

    files = [
        f for f in await asyncio.to_thread(media_files, db, handler.profile_name, "from")
        if f.exists()
    ]
    if not files:
        log("  数据库中无来源为 from 的文件（请先到「扫描」同步）", "yellow")
        set_ready()
        return

    if cancel_requested():
        log("◆ 用户取消", "yellow")
        set_ready()
        return

    log(f"  从数据库取到 {len(files)} 个 from 文件", "gray")
    for f in files[:10]:
        log(f"    └ {f.name}", "gray")
    if len(files) > 10:
        log(f"    └ ... 还有 {len(files) - 10} 个", "gray")

    try:
        raw_mapping = await asyncio.to_thread(handler.normalize, files)
        mapping = {p: n for p, n in raw_mapping.items() if p.name != n}
        log(f"  normalize: 生成 {len(raw_mapping)} 条，{len(mapping)} 条需更名", "gray")
        shown = 0
        for old_path, new_name in list(mapping.items())[:5]:
            log(f"    └ {old_path.name} → {new_name}", "yellow")
            shown += 1
        if shown == 0:
            log("    (所有文件名已符合规范)", "gray")
    except Exception as e:
        logger.exception("normalize 失败 profile=%s", handler.profile_name)
        log(f"  normalize 失败: {e}", "red")
        set_error()
        return

    if cancel_requested():
        log("◆ 用户取消", "yellow")
        set_ready()
        return

    if not mapping:
        log("  无需更名，跳过 rename", "gray")
        set_ready()
        return

    try:
        records = await asyncio.to_thread(handler.rename, mapping, target_dir=to_dir)
        ok = sum(1 for r in records if r.get("status") == "成功")
        fail = len(records) - ok
        log(
            f"  rename: {ok} 成功, {fail} 失败（移动到 {to_dir}）",
            "green" if fail == 0 else "yellow",
        )
        for r in records:
            if r.get("status") != "成功":
                log(
                    f"    └ {r.get('old_name','?')} → {r.get('new_name','?')}: "
                    f"{r.get('status')}",
                    "red",
                )
    except Exception as e:
        logger.exception("rename 失败 profile=%s", handler.profile_name)
        log(f"  rename 失败: {e}", "red")
        set_error()
        return

    log("◆ 文件名更新完成 ✓", "cyan")
    update_drawer_info()
    set_ready()


def _get_source_dir(handler, source_key="from"):
    """获取回滚目标目录：映射/AI 命名用 from，AI 修正用 root。"""
    p = (handler.config.get(source_key) or "").strip()
    return Path(p) if p else None


async def _run_rollback_batch(handler, source_key="from"):
    """回滚上一批（最近一次点击"文件名更新"的全部记录）。"""
    clear_log()
    set_running("回滚上一批")
    log("◆ 回滚上一批...", "yellow")

    if cancel_requested():
        log("◆ 用户取消", "yellow")
        set_ready()
        return

    source_dir = _get_source_dir(handler, source_key)
    try:
        if handler.profile_name == "tv" and source_dir:
            records = handler.db.get_last_batch(handler.profile_name)
            results = await asyncio.to_thread(
                rollback_structure, records, handler.db, source_dir,
            )
        else:
            results = await asyncio.to_thread(
                handler.rollback_last_batch, source_dir=source_dir,
            )
        _log_batch_results(results)
    except Exception as e:
        logger.exception("回滚上一批失败 profile=%s", handler.profile_name)
        log(f"  回滚失败: {e}", "red")
        set_error()
        return
    set_ready()


async def _run_rollback_range(handler, date_from, date_to, source_key="from"):
    """按日期范围回滚。"""
    clear_log()
    sd = (date_from.value or "").strip().replace("/", "-")
    ed = (date_to.value or "").strip().replace("/", "-")
    if not sd or not ed:
        log("  请选择开始和结束日期", "yellow")
        set_error()
        return
    set_running("批量回滚")
    log(f"◆ 回滚 {sd} ~ {ed}...", "yellow")

    if cancel_requested():
        log("◆ 用户取消", "yellow")
        set_ready()
        return

    source_dir = _get_source_dir(handler, source_key)
    try:
        if handler.profile_name == "tv" and source_dir:
            records = handler.db.get_rename_by_date_range(handler.profile_name, sd, ed)
            results = await asyncio.to_thread(
                rollback_structure, records, handler.db, source_dir,
            )
        else:
            results = await asyncio.to_thread(
                handler.rollback_date_range, sd, ed, source_dir=source_dir,
            )
        _log_batch_results(results)
    except Exception as e:
        logger.exception("批量回滚失败 profile=%s", handler.profile_name)
        log(f"  回滚失败: {e}", "red")
        set_error()
        return
    set_ready()


def _log_batch_results(results):
    ok = sum(1 for r in results if "已回滚" in r.get("status", ""))
    fail = sum(1 for r in results if "失败" in r.get("status", ""))
    cleared = sum(1 for r in results if "已不存在" in r.get("status", ""))
    log(f"  回滚 {ok} 条, 清除 {cleared} 条, 失败 {fail} 条",
         "green" if fail == 0 else "yellow")
    for r in results[:30]:
        color = "green" if "已回滚" in r.get("status", "") else "yellow" if "已不存在" in r.get("status", "") else "red"
        log(f"    {r.get('old_name','?')} → {r.get('new_name','?')}: {r.get('status')}", color)
    if len(results) > 30:
        log(f"    ... 还有 {len(results) - 30} 条", "gray")

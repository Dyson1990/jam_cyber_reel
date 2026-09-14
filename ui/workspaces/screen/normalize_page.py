"""
标准化模块（screen）— 文件名规范化 + 重命名。

对应原同步页的「文件名更新」卡片，并新增命名方式单选：
    - 映射命名（原逻辑）：dict 映射 str.replace
    - AI 命名（骨架）：deepseek key + 提示词，逻辑待接入

共享参数（输入即保存到 config_manager）：
    from / to            — 两种命名方式共用
    naming_mode          — "mapping" | "ai"
    naming_rules         — 映射命名规则（JSON dict）
    ai_api_key / ai_prompt — AI 命名参数
"""

import asyncio
import json
from datetime import datetime

from pathlib import Path

from nicegui import ui

from core.files import VIDEO_EXTENSIONS
from core.logging_config import get_log_dir, get_logger
from workspaces._shared import parse_naming_rules
from workspaces.screen.ai_naming import (
    build_prompt, build_fix_prompt, call_deepseek, fetch_infos,
)
from ui.state import tag, update_drawer_info, cancel_requested
from ui.workspaces.screen._shared import (
    log, clear_log, set_running, set_ready, set_error,
    run_button, build_profile_radio, build_log_panel,
)

logger = get_logger(__name__)

# AI 修正扫描：视频 + 压缩文件（看过的电影常被压缩）
_ARCHIVE_EXT = {".zip", ".rar", ".7z"}


def _scan_top_level(path: Path) -> list[Path]:
    """扫描 path 下（仅本层，不递归）的视频与压缩文件。"""
    if not path or not path.is_dir():
        return []
    return [
        f for f in path.iterdir()
        if f.is_file() and f.suffix.lower() in (VIDEO_EXTENSIONS | _ARCHIVE_EXT)
    ]


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
                        if method_radio.value == "ai_fix":
                            _build_path_row(config_mgr, profile)
                        else:
                            _build_from_to_row(config_mgr, profile)
                    with sub_container:
                        if method_radio.value == "ai":
                            _build_ai_naming(config_mgr, profile, handler)
                        elif method_radio.value == "ai_fix":
                            _build_ai_fix(config_mgr, profile, handler)
                        else:
                            _build_mapping_naming(handler, config_mgr, profile)

                _render()

        build_log_panel()


def _on_method_change(config_mgr, profile, value, render):
    config_mgr.update_profile_config(profile, "naming_mode", value)
    render()


def _build_from_to_row(config_mgr, profile):
    """映射命名 / AI 命名共享的 From/To 输入（输入即保存）。"""
    cfg = config_mgr.get_profile_config(profile)
    with ui.row().classes("gap-2 items-center w-full mb-3"):
        ui.label("From:").classes("text-xs text-slate-500 font-mono w-20")
        ui.input(value=cfg.get("from", ""), placeholder="D:/Media/From").classes(
            "flex-1 font-mono text-xs"
        ).props("outlined dense dark").on_value_change(
            lambda e: config_mgr.update_profile_config(profile, "from", e.value or ""),
        )
    with ui.row().classes("gap-2 items-center w-full mb-4"):
        ui.label("To:").classes("text-xs text-slate-500 font-mono w-20")
        ui.input(value=cfg.get("to", ""), placeholder="D:/Media/To").classes(
            "flex-1 font-mono text-xs"
        ).props("outlined dense dark").on_value_change(
            lambda e: config_mgr.update_profile_config(profile, "to", e.value or ""),
        )


def _build_path_row(config_mgr, profile):
    """AI 修正的单一路径输入（替代 From/To）。"""
    cfg = config_mgr.get_profile_config(profile)
    with ui.row().classes("gap-2 items-center w-full mb-4"):
        ui.label("Path:").classes("text-xs text-slate-500 font-mono w-20")
        ui.input(value=cfg.get("ai_fix_path", ""), placeholder="D:/Media/看过").classes(
            "flex-1 font-mono text-xs"
        ).props("outlined dense dark").on_value_change(
            lambda e: config_mgr.update_profile_config(
                profile, "ai_fix_path", e.value or "",
            ),
        )


def _build_rollback_row(handler, source_key="from"):
    """回滚按钮行：回滚上一批 + 批量回滚（含日期范围）排在一行。

    source_key 指定回滚源目录的配置键（AI 命名用 "from"，AI 修正用 "ai_fix_path"）。
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


def _build_mapping_naming(handler, config_mgr, profile):
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
        run_button("▶ 文件名更新", "cyan", lambda: _run_rename(handler))

    _build_rollback_row(handler)


def _build_ai_naming(config_mgr, profile, handler):
    """AI 命名页面：deepseek key（脱敏显示）+ 提示词 + 生成/预览/应用三按钮。"""
    cfg = config_mgr.get_profile_config(profile)

    tag("naming-ai")
    ui.label("AI 命名").classes("text-xs text-cyan-500 font-mono mb-2")

    key = cfg.get("ai_api_key", "")
    with ui.row().classes("gap-2 items-center w-full mb-3"):
        ui.label("Deepseek Key:").classes("text-xs text-slate-500 font-mono w-24")
        key_input = ui.input(
            value=_mask_key(key) if key else "",
            placeholder="未设置（输入新 Key 覆盖）" if not key else "输入新 Key 覆盖",
        ).props("outlined dense dark").classes("flex-1 font-mono text-xs").on_value_change(
            lambda e: _save_key(config_mgr, profile, e.value or "", key_input),
        )

    with ui.row().classes("gap-2 items-center w-full mb-3"):
        ui.label("每次文件名数:").classes("text-xs text-slate-500 font-mono w-24")
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

    ui.label("提示词 (Prompt):").classes("text-xs text-slate-500 font-mono mb-1")
    prompt_area = ui.textarea(value=cfg.get("ai_prompt", "")).classes(
        "w-full bg-slate-700 text-cyan-100 font-mono text-sm"
    ).style("min-height: 100px;").on_value_change(
        lambda e: config_mgr.update_profile_config(
            profile, "ai_prompt", e.value or "",
        ),
    )

    result_state = {"result": {}}

    def _btn(label, on_click, color):
        return run_button(label, color, on_click)

    with ui.row().classes("gap-3 mt-4"):
        _btn("生成需求", lambda: _gen_prompt(config_mgr, profile, handler, prompt_area), "cyan")
        _btn("预览改动", lambda: _preview(config_mgr, profile, prompt_area, result_state, result_container), "cyan")
        _btn("应用映射", lambda: _apply(config_mgr, profile, handler, result_state), "cyan")

    _build_rollback_row(handler)

    result_container = ui.column().classes("w-full mt-4")


def _build_ai_fix(config_mgr, profile, handler):
    """AI 修正页面：检查已标准化文件的可查询补充槽位（中文名/英文名/年份/评分）。"""
    cfg = config_mgr.get_profile_config(profile)

    tag("naming-ai-fix")
    ui.label("AI 修正").classes("text-xs text-cyan-500 font-mono mb-2")

    key = cfg.get("ai_api_key", "")
    with ui.row().classes("gap-2 items-center w-full mb-3"):
        ui.label("Deepseek Key:").classes("text-xs text-slate-500 font-mono w-24")
        key_input = ui.input(
            value=_mask_key(key) if key else "",
            placeholder="未设置（输入新 Key 覆盖）" if not key else "输入新 Key 覆盖",
        ).props("outlined dense dark").classes("flex-1 font-mono text-xs").on_value_change(
            lambda e: _save_key(config_mgr, profile, e.value or "", key_input),
        )

    ui.label("提示词 (Prompt):").classes("text-xs text-slate-500 font-mono mb-1")
    prompt_area = ui.textarea(value=cfg.get("ai_prompt", "")).classes(
        "w-full bg-slate-700 text-cyan-100 font-mono text-sm"
    ).style("min-height: 100px;").on_value_change(
        lambda e: config_mgr.update_profile_config(profile, "ai_prompt", e.value or ""),
    )

    result_state = {"result": {}, "selected": {}}

    with ui.row().classes("gap-3 mt-4"):
        run_button("生成需求", "cyan", lambda: _gen_fix_prompt(config_mgr, profile, prompt_area))
        run_button("预览改动", "cyan", lambda: _preview_fix(config_mgr, profile, prompt_area, result_state, result_container))
        run_button("应用映射", "cyan", lambda: _apply_fix(config_mgr, profile, handler, result_state))

    _build_rollback_row(handler, source_key="ai_fix_path")

    result_container = ui.column().classes("w-full mt-4")


def _mask_key(key: str) -> str:
    """脱敏显示 key：仅保留前 3 后 4 位，其余打码。"""
    if not key:
        return "未设置"
    if len(key) <= 7:
        return "*******"
    return f"{key[:3]}****{key[-4:]}"


def _save_key(config_mgr, profile, value, key_input):
    """录入新 key：非空才覆盖保存，并刷新输入框为脱敏显示。"""
    if value:
        config_mgr.update_profile_config(profile, "ai_api_key", value)
        key_input.set_value(_mask_key(value))


def _save_rules(config_mgr, profile, value):
    try:
        rules = parse_naming_rules(value)
    except json.JSONDecodeError:
        return  # 忽略无效 JSON，待输入完整
    config_mgr.update_profile_config(profile, "naming_rules", rules)


# ==================== AI 命名三步 ====================

async def _gen_prompt(config_mgr, profile, handler, prompt_area):
    """生成需求：扫描 from 目录，组装规则+文件名填入提示词框（可人工改）。"""
    clear_log()
    set_running("生成需求")
    from_dir = Path(config_mgr.get_profile_config(profile).get("from", ""))
    if not from_dir or not from_dir.exists():
        log("  From 未设置或目录不存在", "red")
        set_error()
        return
    try:
        files = await asyncio.to_thread(handler.scan, root_override=from_dir)
    except Exception as e:
        logger.exception("scan 失败 from=%s", from_dir)
        log(f"  scan 失败: {e}", "red")
        set_error()
        return
    if not files:
        log("  From 中无视频文件", "yellow")
        set_ready()
        return
    limit = config_mgr.get_profile_config(profile).get("ai_batch_size", 20)
    names = [f.name for f in files]
    batch = names[:limit] if limit else names
    infos = {}
    if config_mgr.get_profile_config(profile).get("ai_douban", False):
        infos = await asyncio.to_thread(fetch_infos, batch)
    prompt = build_prompt(names, limit=limit, infos=infos)
    if not prompt_area.is_deleted:
        prompt_area.set_value(prompt)
    config_mgr.update_profile_config(profile, "ai_prompt", prompt)
    msg = f"  已生成提示词：共 {len(names)} 个文件，取前 {len(batch)} 个"
    if infos:
        msg += f"，命中豆瓣 {len(infos)} 条"
    log(msg, "cyan")
    set_ready()


async def _preview(config_mgr, profile, prompt_area, result_state, result_container):
    """预览改动：提交提示词框内容（人工修改后）给 deepseek，表格展示映射。"""
    cfg = config_mgr.get_profile_config(profile)
    key = cfg.get("ai_api_key", "")
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
        result = await asyncio.to_thread(call_deepseek, key, prompt)
    except Exception as e:
        logger.exception("deepseek 调用失败")
        log(f"  调用失败: {e}", "red")
        set_error()
        return
    result_state["result"] = result
    _save_mapping(result)
    _render_result_table(result_container, result)
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
    update_drawer_info()
    set_ready()


def _save_mapping(result: dict[str, str]) -> None:
    """把 Deepseek 返回的映射落盘到 logs/，便于人工检查。"""
    log_dir = get_log_dir()
    if not log_dir:
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"ai_mapping_{ts}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  映射已保存: logs/{path.name}", "gray")


def _render_result_table(container, result):
    """在容器内渲染映射表格：原文件名 → 新文件名。"""
    if container.is_deleted:
        return
    container.clear()
    with container:
        if not result:
            ui.label("(无结果)").classes("text-xs text-slate-500 font-mono")
            return
        rows = [{"old": k, "new": v} for k, v in result.items()]
        ui.table(
            columns=[
                {"name": "old", "label": "原文件名", "field": "old", "align": "left"},
                {"name": "new", "label": "新文件名", "field": "new", "align": "left"},
            ],
            rows=rows,
        ).classes("w-full")


# ==================== AI 修正三步 ====================

async def _gen_fix_prompt(config_mgr, profile, prompt_area):
    """生成修正需求：扫描 path 顶层视频+压缩文件，取豆瓣信息，组装修正提示词。"""
    clear_log()
    set_running("生成修正需求")
    path = Path(config_mgr.get_profile_config(profile).get("ai_fix_path", ""))
    if not path or not path.is_dir():
        log("  Path 未设置或目录不存在", "red")
        set_error()
        return
    files = await asyncio.to_thread(_scan_top_level, path)
    if not files:
        log("  Path 下无视频/压缩文件", "yellow")
        set_ready()
        return
    names = [f.name for f in files]
    infos = await asyncio.to_thread(fetch_infos, names)
    prompt = build_fix_prompt(names, infos=infos)
    if not prompt_area.is_deleted:
        prompt_area.set_value(prompt)
    config_mgr.update_profile_config(profile, "ai_prompt", prompt)
    msg = f"  已生成修正提示词：共 {len(names)} 个文件"
    if infos:
        msg += f"，命中豆瓣 {len(infos)} 条"
    log(msg, "cyan")
    set_ready()


async def _preview_fix(config_mgr, profile, prompt_area, result_state, result_container):
    """预览修正：提交提示词给 deepseek，表格展示（含勾选框）。"""
    cfg = config_mgr.get_profile_config(profile)
    key = cfg.get("ai_api_key", "")
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
        result = await asyncio.to_thread(call_deepseek, key, prompt)
    except Exception as e:
        logger.exception("deepseek 调用失败")
        log(f"  调用失败: {e}", "red")
        set_error()
        return
    result_state["result"] = result
    result_state["selected"] = {k: True for k in result}
    _save_mapping(result)
    _render_fix_table(result_container, result, result_state["selected"])
    log(f"  返回 {len(result)} 条映射，已显示表格", "green")
    set_ready()


async def _apply_fix(config_mgr, profile, handler, result_state):
    """应用修正：仅重命名勾选的条目（原地改名）。"""
    clear_log()
    set_running("应用修正")
    result = result_state.get("result", {})
    selected = result_state.get("selected", {})
    if not result:
        log("  尚无预览结果，请先点「预览改动」", "red")
        set_error()
        return
    path = config_mgr.get_profile_config(profile).get("ai_fix_path", "")
    if not path:
        log("  Path 未设置", "red")
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

async def _run_rename(handler):
    """执行文件名更新：扫描 from → normalize → rename（移动到 to）。"""
    clear_log()
    set_running("文件名更新")
    log("◆ 开始文件名更新...", "cyan")

    cfg = handler.config
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

    if not from_dir.exists():
        log(f"  From 目录不存在: {from_dir}", "red")
        set_error()
        return

    if cancel_requested():
        log("◆ 用户取消", "yellow")
        set_ready()
        return

    try:
        files = await asyncio.to_thread(handler.scan, root_override=from_dir)
        log(f"  scan: 在 {from_dir} 中发现 {len(files)} 个视频文件", "gray")
    except Exception as e:
        logger.exception("scan 失败 from=%s", from_dir)
        log(f"  scan 失败: {e}", "red")
        set_error()
        return

    if cancel_requested():
        log("◆ 用户取消", "yellow")
        set_ready()
        return

    if not files:
        log("  From 中无视频文件", "yellow")
        set_ready()
        return

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
    """获取回滚源目录：默认 from，AI 修正传 ai_fix_path。"""
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

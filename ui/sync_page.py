"""
同步页模块 - 数据库同步 + 截图采集 + 文件名更新。

文件作用：
    1. 数据库同步：扫描 Root（排除 from/to 若在 Root 下）→ 与 media 表对比 → 更新数据库
    2. 截图采集：后台线程运行 PyAV 截帧，实时输出日志，不阻塞 UI
    3. 文件名更新：扫描 from → normalize() → rename() 移动到 to → 记录历史

路径语义：
    root  — 已整理视频目录，DB 同步扫描此目录（排除 from/to 若在 root 下）
    from  — 原始新视频目录，rename 的源
    to    — 更名后目标目录，rename 的目标，rollback 的源

与其它模块的关系：
    - 被 ui/state.py 的 switch_page("sync") 调用
    - 通过 ProfileRegistry 获取 handler
    - handler.diff_db() / sync_db() 做数据库同步
    - handler.capture_screenshots() 做截图采集（后台线程）
    - handler.normalize() + handler.rename() 做文件名更新

主要函数：
    build_sync(config_mgr, db, registry) - 构建同步页 UI
"""

import asyncio

from pathlib import Path

from nicegui import ui

from ui.state import update_drawer_info


def _get_exclude_dirs(root: str, *sub_paths: str) -> list[str]:
    """若 sub_path 在 root 下，返回其相对路径首段作为排除目录。"""
    if not root:
        return []
    result: list[str] = []
    for sp in sub_paths:
        if not sp:
            continue
        try:
            rel = Path(sp).resolve().relative_to(Path(root).resolve())
            if rel.parts:
                result.append(rel.parts[0])
        except ValueError:
            pass
    return result


def build_sync(config_mgr, db, registry):
    """构建同步页 UI，包含数据库同步、截图采集和文件名更新三个区域。

    Args:
        config_mgr: ConfigManager 实例
        db: Database 实例
        registry: ProfileRegistry 实例
    """
    profile = config_mgr.current_profile
    handler = registry.get(profile)
    cfg = config_mgr.get_profile_config()
    root = cfg.get("root", "") or "未设置"
    from_path = cfg.get("from", "")
    to_path = cfg.get("to", "")
    exclude_dirs = _get_exclude_dirs(cfg.get("root", ""), from_path, to_path)

    # 标题
    ui.label(f"◆ 同步 — {profile}").classes(
        "text-xl font-mono text-cyan-400 mb-6 glow-text"
    )

    if not handler:
        ui.label("⚠ 当前 Profile 未加载 handler").classes(
            "text-red-400 font-mono"
        )
        return

    # ==================== 区域1：数据库同步 ====================
    with ui.card().classes(
        "bg-gray-950 border border-cyan-800 rounded-lg p-6 w-full mb-6"
    ):
        ui.label("◆ 数据库同步").classes("text-lg font-mono text-cyan-400 mb-2")
        ui.label(
            "扫描 Root 中全部视频文件，与数据库记录对比，更新差异。"
        ).classes("text-sm text-gray-500 font-mono mb-1")
        ui.label(f"Root: {root}").classes("text-xs text-gray-600 font-mono mb-1")
        if exclude_dirs:
            ui.label(f"排除: {exclude_dirs}").classes(
                "text-xs text-yellow-600 font-mono mb-4"
            )
        else:
            ui.label("from/to 均不在 root 下，无需排除").classes(
                "text-xs text-gray-600 font-mono mb-4"
            )

        with ui.row().classes("gap-4 mb-4"):
            db_diff_btn = ui.button(
                "▶ 对比差异",
                on_click=lambda: _run_db_diff(handler, exclude_dirs, db_sync_log),
            )
            db_diff_btn.classes(
                "bg-cyan-900 hover:bg-cyan-700 text-cyan-300 font-mono "
                "border border-cyan-600 rounded px-6 py-2"
            )

            db_sync_btn = ui.button(
                "▶ 数据库同步",
                on_click=lambda: _run_db_sync(handler, exclude_dirs, db_sync_log),
            )
            db_sync_btn.classes(
                "bg-green-900 hover:bg-green-700 text-green-300 font-mono "
                "border border-green-600 rounded px-6 py-2"
            )

        db_sync_log = ui.column().classes("w-full")

    # ==================== 区域2：截图采集 ====================
    with ui.card().classes(
        "bg-gray-950 border border-cyan-800 rounded-lg p-6 w-full mb-6"
    ):
        ui.label("◆ 截图采集").classes("text-lg font-mono text-cyan-400 mb-2")
        ui.label(
            "使用 PyAV 从视频文件中提取帧截图，存入 screenshots 表。"
            "后台线程逐文件处理，实时显示进度。"
        ).classes("text-sm text-gray-500 font-mono mb-1")
        ui.label(f"Root: {root}").classes("text-xs text-gray-600 font-mono mb-1")
        ss_cfg = cfg.get("screenshot_config", {})
        ui.label(
            f"count: {ss_cfg.get('count', 3)}, "
            f"moments: {ss_cfg.get('moments', []) or '（均分）'}"
        ).classes("text-xs text-gray-600 font-mono mb-4")

        with ui.row().classes("gap-4 mb-4"):
            ss_btn = ui.button(
                "▶ 截取截图",
                on_click=lambda: _run_capture_screenshots(handler, ss_log),
            )
            ss_btn.classes(
                "bg-purple-900 hover:bg-purple-700 text-purple-300 font-mono "
                "border border-purple-600 rounded px-6 py-2"
            )

        ss_log = ui.column().classes("w-full")

    # ==================== 区域3：文件名更新 ====================
    with ui.card().classes(
        "bg-gray-950 border border-cyan-800 rounded-lg p-6 w-full"
    ):
        ui.label("◆ 文件名更新").classes("text-lg font-mono text-cyan-400 mb-2")
        ui.label(
            "扫描 from 中的新视频，按命名规则规范化后移动到 to。"
        ).classes("text-sm text-gray-500 font-mono mb-1")
        ui.label(f"Root: {root}").classes("text-xs text-gray-600 font-mono mb-1")
        ui.label(
            f"From: {from_path or '未设置'}  →  To: {to_path or '未设置'}"
        ).classes("text-xs text-yellow-600 font-mono mb-4")

        with ui.row().classes("gap-4 mb-4"):
            rename_btn = ui.button(
                "▶ 文件名更新",
                on_click=lambda: _run_rename(handler, rename_log),
            )
            rename_btn.classes(
                "bg-cyan-900 hover:bg-cyan-700 text-cyan-300 font-mono "
                "border border-cyan-600 rounded px-6 py-2"
            )

            ui.button(
                "↺ 回滚上一批",
                on_click=lambda: _run_rollback_batch(handler, rename_log),
            ).classes(
                "bg-yellow-900 hover:bg-yellow-700 text-yellow-300 font-mono "
                "border border-yellow-600 rounded px-4 py-2"
            )

        with ui.row().classes("gap-2 items-center mb-4"):
            ui.button(
                "↺↺ 批量回滚",
                on_click=lambda: _run_rollback_range(handler, date_from, date_to, rename_log),
            ).classes(
                "bg-red-900 hover:bg-red-700 text-red-300 font-mono "
                "border border-red-600 rounded px-4 py-2"
            )
            ui.label("日期范围：").classes("text-xs text-gray-500 font-mono")
            date_from = ui.input(value="", placeholder="YYYY-MM-DD").classes(
                "w-36 font-mono text-xs"
            ).props("outlined dense dark type=date")
            ui.label("—").classes("text-gray-600 text-xs")
            date_to = ui.input(value="", placeholder="YYYY-MM-DD").classes(
                "w-36 font-mono text-xs"
            ).props("outlined dense dark type=date")

        rename_log = ui.column().classes("w-full")


# ==================== 数据库同步逻辑 ====================

def _run_db_diff(handler, exclude_dirs, log_container):
    """对比 Root 文件与数据库记录，展示增减清单。"""
    from ui.state import status_text

    log_container.clear()
    status_text.set_text("对比数据库差异...")
    if exclude_dirs:
        _log(log_container, f"◆ 正在对比 Root 与数据库（排除 {exclude_dirs}）...", "cyan")
    else:
        _log(log_container, "◆ 正在对比 Root 与数据库...", "cyan")

    try:
        diff = handler.diff_db(exclude_dirs=exclude_dirs if exclude_dirs else None)
    except Exception as e:
        _log(log_container, f"  对比失败: {e}", "red")
        status_text.set_text("就绪")
        return

    added = diff["added"]
    removed = diff["removed"]
    existing = diff["existing"]

    _log(log_container, f"  + 新增 {len(added)} 个文件（Root 中有，DB 中无）", "green")
    for f in added[:20]:
        _log(log_container, f"      {f.name}", "green")
    if len(added) > 20:
        _log(log_container, f"      ... 还有 {len(added) - 20} 个", "gray")

    _log(log_container, f"  - 移除 {len(removed)} 个文件（DB 中有，Root 中无）", "red")
    for p in removed[:20]:
        _log(log_container, f"      {Path(p).name}", "red")
    if len(removed) > 20:
        _log(log_container, f"      ... 还有 {len(removed) - 20} 个", "gray")

    _log(log_container, f"  = 保持不变 {existing} 个文件", "gray")

    if not added and not removed:
        _log(log_container, "  数据库与 Root 完全一致 ✓", "cyan")
    status_text.set_text("就绪")


def _run_db_sync(handler, exclude_dirs, log_container):
    """执行数据库同步：将 Root 中新增文件写入 media 表。"""
    from ui.state import status_text

    log_container.clear()
    status_text.set_text("同步数据库中...")
    _log(log_container, "◆ 正在同步数据库...", "cyan")

    try:
        diff = handler.diff_db(exclude_dirs=exclude_dirs if exclude_dirs else None)
        _log(log_container, f"  发现 {len(diff['added'])} 个新增文件", "gray")

        count = handler.sync_db(exclude_dirs=exclude_dirs if exclude_dirs else None)
        _log(log_container, f"  已写入 {count} 条新记录", "green")

        if diff["removed"]:
            _log(
                log_container,
                f"  注意: {len(diff['removed'])} 个文件在 Root 中已不存在，"
                f"数据库中对应记录已保留",
                "yellow",
            )
    except Exception as e:
        _log(log_container, f"  数据库同步失败: {e}", "red")
        status_text.set_text("就绪")
        return

    _log(log_container, "◆ 数据库同步完成 ✓", "cyan")
    update_drawer_info()
    status_text.set_text("就绪")


# ==================== 截图采集逻辑（后台线程 + 实时日志） ====================

async def _run_capture_screenshots(handler, log_container):
    """逐文件后台截取，实时输出进度，不阻塞 UI。

    每个视频单独调用 asyncio.to_thread，文件之间更新 UI 日志。
    线程与主程序生命周期绑定：主程序退出时守护线程自动终止。
    """
    from ui.state import status_text, status_progress

    log_container.clear()
    _log(log_container, "◆ 开始截图采集...", "cyan")

    cfg = handler.config
    ss_cfg = cfg.get("screenshot_config", {})
    count = ss_cfg.get("count", 3)
    moments = ss_cfg.get("moments", [])

    records = handler.db.get_media_by_profile(handler.profile_name)
    if not records:
        _log(log_container, "  无媒体记录", "yellow")
        return

    # 预过滤：跳过已有足够截图的视频，避免浪费时间
    pending: list = []
    skipped = 0
    for rec in records:
        existing = handler.db.get_screenshot_count(rec["mv_path"])
        if existing >= count:
            skipped += 1
        else:
            pending.append(rec)

    _log(log_container, f"  共 {len(records)} 条媒体记录，已有截图达标 {skipped} 个，待处理 {len(pending)} 个", "gray")

    if not pending:
        _log(log_container, "  全部视频截图已达标，无需处理 ✓", "green")
        status_text.set_text("就绪")
        if status_progress:
            status_progress.set_value(0)
        return

    total = 0
    for i, rec in enumerate(pending):
        mv_path = rec["mv_path"]
        name = Path(mv_path).name
        _log(log_container, f"  截取中: {name}...", "cyan")
        status_text.set_text(f"截图采集: {name}")
        if status_progress:
            status_progress.set_value((i + 1) / len(pending))

        try:
            result = await asyncio.to_thread(
                handler.capture_one_video, mv_path, count, moments
            )
        except Exception as e:
            _log(log_container, f"  {name}: 失败 - {e}", "red")
            continue

        cnt = result.get("count", 0)
        total += cnt
        color = "green" if cnt > 0 else "yellow"
        _log(log_container, f"  {name}: {result.get('status', '?')}", color)

    status_text.set_text("就绪")
    if status_progress:
        status_progress.set_value(0)
    _log(log_container, f"◆ 截图采集完成: 共 {total} 张 ✓", "cyan")


# ==================== 文件名更新逻辑 ====================

def _run_rename(handler, log_container):
    """执行文件名更新：扫描 from → normalize → rename（移动到 to）。

    流程：
        1. scan(from) 扫描待处理目录中的视频文件
        2. normalize() 按规则生成规范文件名
        3. rename(mapping, target_dir=to) 两阶段重命名并移动到 to
    """
    from ui.state import status_text

    log_container.clear()
    _log(log_container, "◆ 开始文件名更新...", "cyan")

    cfg = handler.config
    from_path = cfg.get("from", "")
    to_path = cfg.get("to", "")
    status_text.set_text("文件名更新...")
    if not from_path:
        _log(log_container, "  From 未设置", "red")
        status_text.set_text("就绪")
        return
    if not to_path:
        _log(log_container, "  To 未设置", "red")
        status_text.set_text("就绪")
        return

    from_dir = Path(from_path)
    to_dir = Path(to_path)

    if not from_dir.exists():
        _log(log_container, f"  From 目录不存在: {from_dir}", "red")
        return

    # Step 1: scan from 目录
    try:
        files = handler.scan(root_override=from_dir)
        _log(log_container, f"  scan: 在 {from_dir} 中发现 {len(files)} 个视频文件", "gray")
    except Exception as e:
        _log(log_container, f"  scan 失败: {e}", "red")
        return

    if not files:
        _log(log_container, "  From 中无视频文件", "yellow")
        return

    for f in files[:10]:
        _log(log_container, f"    └ {f.name}", "gray")
    if len(files) > 10:
        _log(log_container, f"    └ ... 还有 {len(files) - 10} 个", "gray")

    # Step 2: normalize
    try:
        raw_mapping = handler.normalize(files)
        # 仅保留文件名真正变化的条目
        mapping = {
            p: n for p, n in raw_mapping.items() if p.name != n
        }
        _log(log_container, f"  normalize: 生成 {len(raw_mapping)} 条，{len(mapping)} 条需更名", "gray")
        shown = 0
        for old_path, new_name in list(mapping.items())[:5]:
            _log(log_container, f"    └ {old_path.name} → {new_name}", "yellow")
            shown += 1
        if shown == 0:
            _log(log_container, "    (所有文件名已符合规范)", "gray")
    except Exception as e:
        _log(log_container, f"  normalize 失败: {e}", "red")
        return

    if not mapping:
        _log(log_container, "  无需更名，跳过 rename", "gray")
        status_text.set_text("就绪")
        return

    # Step 3: rename → 移动到 to
    try:
        records = handler.rename(mapping, target_dir=to_dir)
        ok = sum(1 for r in records if r.get("status") == "成功")
        fail = len(records) - ok
        _log(
            log_container,
            f"  rename: {ok} 成功, {fail} 失败（移动到 {to_dir}）",
            "green" if fail == 0 else "yellow",
        )
        for r in records:
            if r.get("status") != "成功":
                _log(
                    log_container,
                    f"    └ {r.get('old_name','?')} → {r.get('new_name','?')}: "
                    f"{r.get('status')}",
                    "red",
                )
    except Exception as e:
        _log(log_container, f"  rename 失败: {e}", "red")
        return

    _log(log_container, "◆ 文件名更新完成 ✓", "cyan")
    update_drawer_info()
    status_text.set_text("就绪")


def _get_source_dir(handler):
    """获取 from 目录作为 rollback 的源目录。"""
    from_path = (handler.config.get("from") or "").strip()
    return Path(from_path) if from_path else None


def _run_rollback_batch(handler, log_container):
    """回滚上一批（最近一次点击"文件名更新"的全部记录）。"""
    log_container.clear()
    _log(log_container, "◆ 回滚上一批...", "yellow")

    source_dir = _get_source_dir(handler)
    try:
        results = handler.rollback_last_batch(source_dir=source_dir)
        _log_batch_results(results, log_container)
    except Exception as e:
        _log(log_container, f"  回滚失败: {e}", "red")


def _run_rollback_range(handler, date_from, date_to, log_container):
    """按日期范围回滚。"""
    log_container.clear()
    sd = (date_from.value or "").strip().replace("/", "-")
    ed = (date_to.value or "").strip().replace("/", "-")
    if not sd or not ed:
        _log(log_container, "  请选择开始和结束日期", "yellow")
        return
    _log(log_container, f"◆ 回滚 {sd} ~ {ed}...", "yellow")

    source_dir = _get_source_dir(handler)
    try:
        results = handler.rollback_date_range(sd, ed, source_dir=source_dir)
        _log_batch_results(results, log_container)
    except Exception as e:
        _log(log_container, f"  回滚失败: {e}", "red")


def _log_batch_results(results, log_container):
    ok = sum(1 for r in results if "已回滚" in r.get("status", ""))
    fail = sum(1 for r in results if "失败" in r.get("status", ""))
    cleared = sum(1 for r in results if "已不存在" in r.get("status", ""))
    _log(log_container, f"  回滚 {ok} 条, 清除 {cleared} 条, 失败 {fail} 条",
         "green" if fail == 0 else "yellow")
    for r in results[:30]:
        color = "green" if "已回滚" in r.get("status", "") else "yellow" if "已不存在" in r.get("status", "") else "red"
        _log(log_container, f"    {r.get('old_name','?')} → {r.get('new_name','?')}: {r.get('status')}", color)
    if len(results) > 30:
        _log(log_container, f"    ... 还有 {len(results) - 30} 条", "gray")


def _log(container: ui.column, msg: str, color: str = "gray"):
    """向日志容器追加一条带颜色的日志。"""
    color_map = {
        "cyan": "text-cyan-400",
        "gray": "text-gray-400",
        "green": "text-green-400",
        "red": "text-red-400",
        "yellow": "text-yellow-400",
    }
    cls = color_map.get(color, "text-gray-400")
    with container:
        ui.label(msg).classes(f"font-mono text-sm {cls}")

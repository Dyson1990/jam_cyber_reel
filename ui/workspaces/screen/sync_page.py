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
    - core.screenshots.capture_one_video() 做截图采集（后台线程）
    - handler.normalize() + handler.rename() 做文件名更新

主要函数：
    build_sync(config_mgr, db, registry) - 构建同步页 UI
"""

import asyncio

from pathlib import Path

from nicegui import ui

from ui.state import update_drawer_info, tag
from core.screenshots import capture_one_video
from core.common.browser import get_relative_exclude_dirs
from ui.state import clear_cancel, cancel_requested


# 模块级共享日志容器引用（build_sync 中赋值，页面切换时自动重建）
_log_container: ui.column = None
_log_scroll_nicegui_id: int = 0


def _log(msg: str, color: str = "gray"):
    """向右侧共享日志区追加一条带颜色的日志。"""
    if _log_container is None:
        return
    color_cls = {
        "cyan": "text-cyan-400",
        "gray": "text-gray-400",
        "green": "text-green-400",
        "red": "text-red-400",
        "yellow": "text-yellow-400",
    }.get(color, "text-gray-400")
    with _log_container:
        ui.label(msg).classes(f"font-mono text-xs {color_cls}")


def _clear_log():
    """清空共享日志区，重置取消标记。"""
    clear_cancel()
    if _log_container is not None:
        _log_container.clear()


def _set_running(label: str):
    """设置状态栏为 '运行：<功能名>'。"""
    from ui.state import status_text
    if status_text:
        status_text.set_text(f"运行：{label}")


def _set_ready():
    """恢复状态栏为就绪。"""
    from ui.state import status_text, status_progress
    if status_text:
        status_text.set_text("就绪")
    if status_progress:
        status_progress.set_value(0)


# ==================== 页面构建 ====================

def build_sync(config_mgr, db, registry):
    """构建同步页 UI，包含数据库同步、截图采集和文件名更新三个区域。

    Args:
        config_mgr: ConfigManager 实例
        db: Database 实例
        registry: ProfileRegistry 实例
    """
    global _log_container

    profile = config_mgr.current_profile
    handler = registry.get(profile)
    cfg = config_mgr.get_profile_config()
    root = cfg.get("root", "") or "未设置"
    from_path = cfg.get("from", "")
    to_path = cfg.get("to", "")
    exclude_dirs = get_relative_exclude_dirs(cfg.get("root", ""), from_path, to_path)

    # 标题
    tag("sync")
    ui.label(f"◆ 同步 — {profile}").classes(
        "text-xl font-mono text-cyan-400 mb-6 glow-text"
    )

    if not handler:
        ui.label("⚠ 当前 Profile 未加载 handler").classes(
            "text-red-400 font-mono"
        )
        return

    # 左右布局：右侧 absolute 定位，行高仅由左侧三卡决定，右侧严格等高
    with ui.row().classes("w-full").style("position: relative;"):
        # === 左侧操作区（留出右侧空间，避免内容被遮挡） ===
        with ui.column().classes("flex-1 min-w-0").style("margin-right: calc(38% + 1rem);"):
            _build_db_sync_card(handler, root, exclude_dirs, config_mgr)
            _build_screenshot_card(handler, root, cfg)
            _build_rename_card(handler, root, from_path, to_path)

        # === 右侧共享日志面板（absolute 定位，与左侧三卡严格等高） ===
        with ui.card().classes(
            "bg-gray-950 border border-cyan-800 rounded-lg p-4"
        ).style(
            "position: absolute; top: 0; right: 0; bottom: 0; width: 38%; "
            "display: flex; flex-direction: column;"
        ):
            tag("sync-log")
            ui.label("◆ 运行日志").classes("text-lg font-mono text-cyan-400 mb-3 flex-none")
            scroll_area = ui.column().classes("overflow-y-auto w-full").style("flex: 1 1 0%; min-height: 0;")
            _log_container = scroll_area
            _log_scroll_nicegui_id = scroll_area.id

            # 定时滚动日志到底部（getHtmlElement 是 NiceGUI 客户端内置函数）
            def _scroll_log():
                ui.run_javascript(
                    f'var e=getHtmlElement({_log_scroll_nicegui_id});'
                    f'if(e)e.scrollTop=e.scrollHeight;',
                    timeout=0,
                )
            ui.timer(0.3, _scroll_log)


def _build_db_sync_card(handler, root, exclude_dirs, config_mgr):
    """数据库同步卡片。"""
    profile = handler.profile_name
    crid_pattern = handler.config.get("crid_pattern", "")

    with ui.card().classes(
        "bg-gray-950 border border-cyan-800 rounded-lg p-6 w-full mb-6"
    ):
        tag("sync-db")
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

        # crid 正则输入（自动保存到 Profile 配置）
        with ui.row().classes("gap-2 items-center mb-3"):
            ui.label("crid 正则:").classes("text-xs text-gray-500 font-mono")
            crid_input = ui.input(
                value=crid_pattern, placeholder="例如: CRID-(\\d+)",
            ).classes("w-56 font-mono text-xs").props("outlined dense dark")
            crid_input.on("change", lambda e: (
                config_mgr.update_profile_config(profile, "crid_pattern", e.value or "")
            ))

        with ui.row().classes("gap-4"):
            ui.button(
                "▶ 对比差异",
                on_click=lambda: _run_db_diff(handler, exclude_dirs),
            ).classes(
                "bg-cyan-900 hover:bg-cyan-700 text-cyan-300 font-mono "
                "border border-cyan-600 rounded px-6 py-2"
            )

            ui.button(
                "▶ 数据库同步",
                on_click=lambda: _run_db_sync(
                    handler, exclude_dirs, (crid_input.value or "").strip(),
                ),
            ).classes(
                "bg-green-900 hover:bg-green-700 text-green-300 font-mono "
                "border border-green-600 rounded px-6 py-2"
            )


def _build_screenshot_card(handler, root, cfg):
    """截图采集卡片。"""
    with ui.card().classes(
        "bg-gray-950 border border-cyan-800 rounded-lg p-6 w-full mb-6"
    ):
        tag("sync-screenshot")
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

        ui.button(
            "▶ 截取截图",
            on_click=lambda: _run_capture_screenshots(handler),
        ).classes(
            "bg-purple-900 hover:bg-purple-700 text-purple-300 font-mono "
            "border border-purple-600 rounded px-6 py-2"
        )


def _build_rename_card(handler, root, from_path, to_path):
    """文件名更新卡片。"""
    with ui.card().classes(
        "bg-gray-950 border border-cyan-800 rounded-lg p-6 w-full"
    ):
        tag("sync-rename")
        ui.label("◆ 文件名更新").classes("text-lg font-mono text-cyan-400 mb-2")
        ui.label(
            "扫描 from 中的新视频，按命名规则规范化后移动到 to。"
        ).classes("text-sm text-gray-500 font-mono mb-1")
        ui.label(f"Root: {root}").classes("text-xs text-gray-600 font-mono mb-1")
        ui.label(
            f"From: {from_path or '未设置'}  →  To: {to_path or '未设置'}"
        ).classes("text-xs text-yellow-600 font-mono mb-4")

        with ui.row().classes("gap-4 mb-4"):
            ui.button(
                "▶ 文件名更新",
                on_click=lambda: _run_rename(handler),
            ).classes(
                "bg-cyan-900 hover:bg-cyan-700 text-cyan-300 font-mono "
                "border border-cyan-600 rounded px-6 py-2"
            )

            ui.button(
                "↺ 回滚上一批",
                on_click=lambda: _run_rollback_batch(handler),
            ).classes(
                "bg-yellow-900 hover:bg-yellow-700 text-yellow-300 font-mono "
                "border border-yellow-600 rounded px-4 py-2"
            )

        with ui.row().classes("gap-2 items-center"):
            ui.button(
                "↺↺ 批量回滚",
                on_click=lambda: _run_rollback_range(handler, date_from, date_to),
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


# ==================== 数据库同步逻辑 ====================

async def _run_db_diff(handler, exclude_dirs):
    """对比 Root 文件与数据库记录，展示增减清单。"""
    _clear_log()
    _set_running("对比差异")

    _log("◆ 开始对比数据库差异...", "cyan")
    if exclude_dirs:
        _log(f"  排除目录: {exclude_dirs}", "gray")

    if cancel_requested():
        _log("◆ 用户取消", "yellow")
        _set_ready()
        return

    try:
        diff = await asyncio.to_thread(
            handler.diff_db,
            exclude_dirs=exclude_dirs if exclude_dirs else None,
        )
    except Exception as e:
        _log(f"  对比失败: {e}", "red")
        _set_ready()
        return

    if cancel_requested():
        _log("◆ 用户取消", "yellow")
        _set_ready()
        return

    added = diff["added"]
    removed = diff["removed"]
    existing = diff["existing"]

    _log(f"  + 新增 {len(added)} 个文件（Root 中有，DB 中无）", "green")
    for f in added[:20]:
        _log(f"      {f.name}", "green")
    if len(added) > 20:
        _log(f"      ... 还有 {len(added) - 20} 个", "gray")

    _log(f"  - 移除 {len(removed)} 个文件（DB 中有，Root 中无）", "red")
    for p in removed[:20]:
        _log(f"      {Path(p).name}", "red")
    if len(removed) > 20:
        _log(f"      ... 还有 {len(removed) - 20} 个", "gray")

    _log(f"  = 保持不变 {existing} 个文件", "gray")

    if not added and not removed:
        _log("  数据库与 Root 完全一致 ✓", "cyan")
    _log("◆ 对比完成 ✓", "cyan")
    _set_ready()


async def _run_db_sync(handler, exclude_dirs, crid_pattern: str = ""):
    """执行数据库同步：将 Root 中新增文件写入 media 表。"""
    _clear_log()
    _set_running("数据库同步")

    _log("◆ 开始数据库同步...", "cyan")
    if crid_pattern:
        _log(f"  crid 提取: {crid_pattern}", "gray")

    if cancel_requested():
        _log("◆ 用户取消", "yellow")
        _set_ready()
        return

    try:
        diff = await asyncio.to_thread(
            handler.diff_db,
            exclude_dirs=exclude_dirs if exclude_dirs else None,
        )
        _log(f"  发现 {len(diff['added'])} 个新增文件", "gray")

        if cancel_requested():
            _log("◆ 用户取消", "yellow")
            _set_ready()
            return

        count = await asyncio.to_thread(
            handler.sync_db,
            exclude_dirs=exclude_dirs if exclude_dirs else None,
            crid_pattern=crid_pattern,
            added=diff["added"],
        )
        _log(f"  已写入 {count} 条新记录", "green")

        if diff["removed"]:
            _log(
                f"  注意: {len(diff['removed'])} 个文件在 Root 中已不存在，"
                f"数据库中对应记录已保留",
                "yellow",
            )
    except Exception as e:
        _log(f"  数据库同步失败: {e}", "red")
        _set_ready()
        return

    _log("◆ 数据库同步完成 ✓", "cyan")
    update_drawer_info()
    _set_ready()


# ==================== 截图采集逻辑（后台线程 + 实时日志） ====================

async def _run_capture_screenshots(handler):
    """逐文件后台截取，实时输出进度，不阻塞 UI。

    每个视频单独调用 asyncio.to_thread，文件之间更新 UI 日志。
    线程与主程序生命周期绑定：主程序退出时守护线程自动终止。
    """
    from ui.state import status_progress

    _clear_log()
    _set_running("截取截图")
    _log("◆ 开始截图采集...", "cyan")

    try:
        cfg = handler.config
        ss_cfg = cfg.get("screenshot_config", {})
        count = ss_cfg.get("count", 3)
        moments = ss_cfg.get("moments", [])

        _log("  读取媒体记录...", "gray")
        records = handler.db.get_media_by_profile(handler.profile_name)
        _log(f"  共 {len(records)} 条记录", "gray")

        if not records:
            _log("  无媒体记录", "yellow")
            _set_ready()
            return

        # 预过滤：跳过已有足够截图的视频，避免浪费时间
        _log("  预过滤已有截图...", "gray")
        pending: list = []
        skipped = 0
        for rec in records:
            existing = handler.db.get_screenshot_count(rec["mv_path"])
            if existing >= count:
                skipped += 1
            else:
                pending.append(rec)

        if skipped:
            _log(f"  ⊘ 跳过 {skipped} 个（截图已达 {count} 张上限，直接从数据库获取即可）", "gray")
        _log(f"  待处理 {len(pending)} 个", "cyan")

        if not pending:
            _log("  全部视频截图已达标，无需处理 ✓", "green")
            _set_ready()
            return

        total = 0
        VIDEO_TIMEOUT = 120
        for i, rec in enumerate(pending):
            if cancel_requested():
                _log("◆ 用户取消", "yellow")
                break
            mv_path = rec["mv_path"]
            name = Path(mv_path).name
            _log(f"  [{i+1}/{len(pending)}] {name}", "cyan")
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
                _log(f"  {name}: 超时（>{VIDEO_TIMEOUT}s）", "red")
                continue
            except Exception as e:
                _log(f"  {name}: 失败 - {e}", "red")
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
            _log(f"  {name}: {status}", color)

        _log(f"◆ 截图采集完成: 共 {total} 张 ✓", "cyan")
    except Exception as e:
        import traceback
        _log(f"◆ 截图采集异常: {e}", "red")
        _log(traceback.format_exc(), "red")
    finally:
        _set_ready()


# ==================== 文件名更新逻辑 ====================

async def _run_rename(handler):
    """执行文件名更新：扫描 from → normalize → rename（移动到 to）。

    流程：
        1. scan(from) 扫描待处理目录中的视频文件
        2. normalize() 按规则生成规范文件名
        3. rename(mapping, target_dir=to) 两阶段重命名并移动到 to
    """
    _clear_log()
    _set_running("文件名更新")
    _log("◆ 开始文件名更新...", "cyan")

    cfg = handler.config
    from_path = cfg.get("from", "")
    to_path = cfg.get("to", "")
    if not from_path:
        _log("  From 未设置", "red")
        _set_ready()
        return
    if not to_path:
        _log("  To 未设置", "red")
        _set_ready()
        return

    from_dir = Path(from_path)
    to_dir = Path(to_path)

    if not from_dir.exists():
        _log(f"  From 目录不存在: {from_dir}", "red")
        _set_ready()
        return

    if cancel_requested():
        _log("◆ 用户取消", "yellow")
        _set_ready()
        return

    # Step 1: scan from 目录
    try:
        files = await asyncio.to_thread(handler.scan, root_override=from_dir)
        _log(f"  scan: 在 {from_dir} 中发现 {len(files)} 个视频文件", "gray")
    except Exception as e:
        _log(f"  scan 失败: {e}", "red")
        _set_ready()
        return

    if cancel_requested():
        _log("◆ 用户取消", "yellow")
        _set_ready()
        return

    if not files:
        _log("  From 中无视频文件", "yellow")
        _set_ready()
        return

    for f in files[:10]:
        _log(f"    └ {f.name}", "gray")
    if len(files) > 10:
        _log(f"    └ ... 还有 {len(files) - 10} 个", "gray")

    # Step 2: normalize
    try:
        raw_mapping = await asyncio.to_thread(handler.normalize, files)
        # 仅保留文件名真正变化的条目
        mapping = {
            p: n for p, n in raw_mapping.items() if p.name != n
        }
        _log(f"  normalize: 生成 {len(raw_mapping)} 条，{len(mapping)} 条需更名", "gray")
        shown = 0
        for old_path, new_name in list(mapping.items())[:5]:
            _log(f"    └ {old_path.name} → {new_name}", "yellow")
            shown += 1
        if shown == 0:
            _log("    (所有文件名已符合规范)", "gray")
    except Exception as e:
        _log(f"  normalize 失败: {e}", "red")
        _set_ready()
        return

    if cancel_requested():
        _log("◆ 用户取消", "yellow")
        _set_ready()
        return

    if not mapping:
        _log("  无需更名，跳过 rename", "gray")
        _set_ready()
        return

    # Step 3: rename → 移动到 to
    try:
        records = await asyncio.to_thread(
            handler.rename, mapping, target_dir=to_dir,
        )
        ok = sum(1 for r in records if r.get("status") == "成功")
        fail = len(records) - ok
        _log(
            f"  rename: {ok} 成功, {fail} 失败（移动到 {to_dir}）",
            "green" if fail == 0 else "yellow",
        )
        for r in records:
            if r.get("status") != "成功":
                _log(
                    f"    └ {r.get('old_name','?')} → {r.get('new_name','?')}: "
                    f"{r.get('status')}",
                    "red",
                )
    except Exception as e:
        _log(f"  rename 失败: {e}", "red")
        _set_ready()
        return

    _log("◆ 文件名更新完成 ✓", "cyan")
    update_drawer_info()
    _set_ready()


def _get_source_dir(handler):
    """获取 from 目录作为 rollback 的源目录。"""
    from_path = (handler.config.get("from") or "").strip()
    return Path(from_path) if from_path else None


async def _run_rollback_batch(handler):
    """回滚上一批（最近一次点击"文件名更新"的全部记录）。"""
    _clear_log()
    _set_running("回滚上一批")
    _log("◆ 回滚上一批...", "yellow")

    if cancel_requested():
        _log("◆ 用户取消", "yellow")
        _set_ready()
        return

    source_dir = _get_source_dir(handler)
    try:
        results = await asyncio.to_thread(
            handler.rollback_last_batch, source_dir=source_dir,
        )
        _log_batch_results(results)
    except Exception as e:
        _log(f"  回滚失败: {e}", "red")
    _set_ready()


async def _run_rollback_range(handler, date_from, date_to):
    """按日期范围回滚。"""
    _clear_log()
    sd = (date_from.value or "").strip().replace("/", "-")
    ed = (date_to.value or "").strip().replace("/", "-")
    if not sd or not ed:
        _log("  请选择开始和结束日期", "yellow")
        return
    _set_running("批量回滚")
    _log(f"◆ 回滚 {sd} ~ {ed}...", "yellow")

    if cancel_requested():
        _log("◆ 用户取消", "yellow")
        _set_ready()
        return

    source_dir = _get_source_dir(handler)
    try:
        results = await asyncio.to_thread(
            handler.rollback_date_range, sd, ed, source_dir=source_dir,
        )
        _log_batch_results(results)
    except Exception as e:
        _log(f"  回滚失败: {e}", "red")
    _set_ready()


def _log_batch_results(results):
    ok = sum(1 for r in results if "已回滚" in r.get("status", ""))
    fail = sum(1 for r in results if "失败" in r.get("status", ""))
    cleared = sum(1 for r in results if "已不存在" in r.get("status", ""))
    _log(f"  回滚 {ok} 条, 清除 {cleared} 条, 失败 {fail} 条",
         "green" if fail == 0 else "yellow")
    for r in results[:30]:
        color = "green" if "已回滚" in r.get("status", "") else "yellow" if "已不存在" in r.get("status", "") else "red"
        _log(f"    {r.get('old_name','?')} → {r.get('new_name','?')}: {r.get('status')}", color)
    if len(results) > 30:
        _log(f"    ... 还有 {len(results) - 30} 条", "gray")

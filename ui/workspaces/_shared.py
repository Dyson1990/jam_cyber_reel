"""
配置页共享前端 — screen/lab 复用。

文件作用：
    提供 Profile 切换、配置查看与修改功能（Root/From/To/命名规则/表结构/截图/扩展）。
    校验与保存逻辑委托 workspaces._shared.save_config()。

与其它模块的关系：
    - 被 screen/lab 的 config_page.py 复用
    - 修改 ConfigManager 数据，保存后调用 update_drawer_info
"""

import json

from nicegui import ui

from ui.state import update_drawer_info, switch_page, tag
from workspaces._shared import save_config


def build_config(config_mgr, registry):
    """构建配置页 UI（对当前 Profile 编辑）。"""
    profile = config_mgr.current_profile
    cfg = config_mgr.get_profile_config()

    tag("config")
    ui.label("◆ CONFIGURATION").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")

    with ui.row().classes("gap-4 items-center mb-6"):
        tag("config-profile")
        ui.label("切换 Profile:").classes("text-sm font-mono text-gray-400")
        profile_select = ui.select(
            options=config_mgr.list_profiles(),
            value=profile,
            on_change=lambda e: _on_profile_switch(e.value, config_mgr),
        )
        profile_select.classes("bg-gray-700 text-cyan-100 font-mono")
        profile_select.style("min-width: 200px;")
        ui.label(f"显示名称: {cfg.get('name', '')}").classes(
            "text-sm font-mono text-gray-500"
        )

    ui.separator().classes("my-4 border-cyan-900")

    with ui.row().classes("gap-4 items-center w-full mb-4"):
        tag("config-paths")
        ui.label("Root:").classes("text-sm font-mono text-gray-400 w-32")
        root_input = ui.input(value=cfg.get("root", ""), placeholder="D:/Media/Movies").classes(
            "flex-1 bg-gray-700 text-gray-100 font-mono"
        )

    with ui.row().classes("gap-4 items-center w-full mb-4"):
        ui.label("From:").classes("text-sm font-mono text-gray-400 w-32")
        from_input = ui.input(value=cfg.get("from", ""), placeholder="D:/Media/From").classes(
            "flex-1 bg-gray-700 text-gray-100 font-mono"
        )

    with ui.row().classes("gap-4 items-center w-full mb-4"):
        ui.label("To:").classes("text-sm font-mono text-gray-400 w-32")
        to_input = ui.input(value=cfg.get("to", ""), placeholder="D:/Media/To").classes(
            "flex-1 bg-gray-700 text-gray-100 font-mono"
        )

    tag("config-naming")
    ui.label("命名规则 (Naming Rules):").classes("text-sm font-mono text-gray-400 mb-2")
    rules_editor = (
        ui.textarea(value=json.dumps(cfg.get("naming_rules", {}), ensure_ascii=False, indent=2))
        .classes("w-full bg-gray-700 text-yellow-100 font-mono text-sm")
        .style("min-height: 100px;")
    )

    tag("config-schema")
    ui.label("表结构 (Table Schema):").classes("text-sm font-mono text-gray-400 mt-4 mb-2")
    ui.label(
        "基础列 id/title/mv_path/cover/added_time 自动生成，此处仅定义扩展列。"
        "每项包含 name, type, label。"
    ).classes("text-xs text-gray-600 font-mono mb-1")
    schema_editor = (
        ui.textarea(value=json.dumps(cfg.get("table_schema", []), ensure_ascii=False, indent=2))
        .classes("w-full bg-gray-700 text-yellow-100 font-mono text-sm")
        .style("min-height: 120px;")
    )

    tag("config-screenshot")
    ui.label("截图配置 (Screenshot Config):").classes("text-sm font-mono text-gray-400 mt-4 mb-2")
    ui.label(
        "count: 平均截取张数；moments: 指定视频时间点（秒）。moments 非空时忽略 count。"
    ).classes("text-xs text-gray-600 font-mono mb-1")
    ss_editor = (
        ui.textarea(
            value=json.dumps(
                cfg.get("screenshot_config", {"count": 3, "moments": []}),
                ensure_ascii=False, indent=2,
            )
        )
        .classes("w-full bg-gray-700 text-yellow-100 font-mono text-sm")
        .style("min-height: 80px;")
    )

    tag("config-extra")
    ui.label("扩展配置 (Extra Config):").classes("text-sm font-mono text-gray-400 mt-4 mb-2")
    extra_editor = (
        ui.textarea(value=json.dumps(cfg.get("extra_config", {}), ensure_ascii=False, indent=2))
        .classes("w-full bg-gray-700 text-yellow-100 font-mono text-sm")
        .style("min-height: 80px;")
    )

    with ui.row().classes("gap-4 mt-6"):
        tag("config-actions")
        ui.button(
            "◆ 保存配置",
            on_click=lambda: _save_config(
                config_mgr, profile, root_input.value, from_input.value, to_input.value,
                rules_editor.value, schema_editor.value, ss_editor.value, extra_editor.value,
                status_label,
            ),
        ).classes(
            "bg-cyan-900 hover:bg-cyan-700 text-cyan-300 font-mono "
            "border border-cyan-600 rounded px-6 py-2"
        )
        ui.button("◇ 重置", on_click=lambda: switch_page("config")).classes(
            "bg-gray-800 hover:bg-gray-700 text-gray-400 font-mono "
            "border border-gray-600 rounded px-6 py-2"
        )

    status_label = ui.label("").classes("text-sm font-mono mt-4")


def _on_profile_switch(new_profile: str, config_mgr):
    """切换 Profile：更新 current_profile + 刷新抽屉 + 重建页面。"""
    config_mgr.current_profile = new_profile
    update_drawer_info()
    switch_page("config")


def _save_config(config_mgr, profile, root, from_path, to_path,
                 rules_str, schema_str, ss_str, extra_str, status_label):
    """保存配置回调，校验/持久化委托 workspaces._shared.save_config。"""
    err = save_config(
        config_mgr, profile, root, from_path, to_path,
        rules_str, schema_str, ss_str, extra_str,
    )
    if err:
        status_label.set_text(err)
        status_label.classes("text-red-400 text-sm font-mono mt-4")
        return
    update_drawer_info()
    status_label.set_text("配置已保存 ✓")
    status_label.classes("text-green-400 text-sm font-mono mt-4")

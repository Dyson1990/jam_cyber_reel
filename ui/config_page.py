"""
配置页模块 - Profile 切换与配置编辑。

文件作用：
    提供 Profile 切换、配置查看与修改功能。
    支持修改 Root、命名规则、表结构、扩展配置。

与其它模块的关系：
    - 被 ui/state.py 的 switch_page("config") 调用
    - 修改 ConfigManager 数据（config_mgr.update_profile_config）
    - 修改后调用 state.update_drawer_info 更新左侧菜单

页面布局：
    ┌─────────────────────────────────────────┐
    │  ◆ CONFIGURATION                        │
    ├─────────────────────────────────────────┤
    │  切换 Profile: [下拉选择]                 │
    │  ─────────────────────────────────────  │
    │  Root:        [输入框]                   │
    │  New Root:    [输入框]                   │
    │  命名规则:     [JSON 编辑区]             │
    │  表结构:       [JSON 编辑区]             │
    │  扩展配置:     [JSON 编辑区]             │
    │  [保存配置]                               │
    └─────────────────────────────────────────┘

主要函数：
    build_config(config_mgr, registry) - 构建配置页 UI
"""

import json

from nicegui import ui

from ui.state import update_drawer_info, switch_page


def build_config(config_mgr, registry):
    """构建配置页 UI。

    组件说明：
        - Profile 下拉框：切换当前 Profile，切换后自动刷新页面
        - Root 输入框：设置媒体文件根目录
        - 命名规则文本框：JSON 格式的 dict 或 regex 规则
        - 表结构文本框：JSON 格式的列定义列表 [{name, type, label}]
        - 扩展配置文本框：JSON 格式的额外配置
        - 保存按钮：将修改写入 ConfigManager 并持久化

    事件流程：
        切换 Profile → config_mgr.current_profile = new → update_drawer_info() → refresh
        编辑配置 → 修改内存中的值 → 点击保存 → config_mgr.update...() → config_mgr.save()

    Args:
        config_mgr: ConfigManager 实例
        registry: ProfileRegistry 实例

    调用时机：用户点击左侧"配置"菜单时。
    """
    profile = config_mgr.current_profile
    cfg = config_mgr.get_profile_config()

    # 标题
    ui.label("◆ CONFIGURATION").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")

    # Profile 切换栏
    with ui.row().classes("gap-4 items-center mb-6"):
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

    # 配置编辑区
    # Root（已整理视频目录）
    with ui.row().classes("gap-4 items-center w-full mb-4"):
        ui.label("Root:").classes("text-sm font-mono text-gray-400 w-32")
        root_input = ui.input(
            value=cfg.get("root", ""),
            placeholder="D:/Media/Movies",
        ).classes("flex-1 bg-gray-700 text-gray-100 font-mono")

    # From（原始新视频目录）
    with ui.row().classes("gap-4 items-center w-full mb-4"):
        ui.label("From:").classes("text-sm font-mono text-gray-400 w-32")
        from_input = ui.input(
            value=cfg.get("from", ""),
            placeholder="D:/Media/From",
        ).classes("flex-1 bg-gray-700 text-gray-100 font-mono")

    # To（更名后目标目录）
    with ui.row().classes("gap-4 items-center w-full mb-4"):
        ui.label("To:").classes("text-sm font-mono text-gray-400 w-32")
        to_input = ui.input(
            value=cfg.get("to", ""),
            placeholder="D:/Media/To",
        ).classes("flex-1 bg-gray-700 text-gray-100 font-mono")

    # 命名规则（JSON）
    ui.label("命名规则 (Naming Rules):").classes("text-sm font-mono text-gray-400 mb-2")
    rules_str = json.dumps(cfg.get("naming_rules", {}), ensure_ascii=False, indent=2)
    rules_editor = (
        ui.textarea(value=rules_str)
        .classes("w-full bg-gray-700 text-yellow-100 font-mono text-sm")
        .style("min-height: 100px;")
    )

    # 表结构（JSON）—— 每种 Profile 独立的列定义
    ui.label("表结构 (Table Schema):").classes(
        "text-sm font-mono text-gray-400 mt-4 mb-2"
    )
    ui.label(
        "基础列 id/title/mv_path/cover/added_time 自动生成，"
        "此处仅定义扩展列。每项包含 name, type, label。"
    ).classes("text-xs text-gray-600 font-mono mb-1")
    schema_str = json.dumps(
        cfg.get("table_schema", []), ensure_ascii=False, indent=2
    )
    schema_editor = (
        ui.textarea(value=schema_str)
        .classes("w-full bg-gray-700 text-yellow-100 font-mono text-sm")
        .style("min-height: 120px;")
    )

    # 截图配置（JSON）
    ui.label("截图配置 (Screenshot Config):").classes(
        "text-sm font-mono text-gray-400 mt-4 mb-2"
    )
    ui.label(
        "count: 平均截取张数；moments: 指定视频时间点（秒），如 [60, 300, 600]。"
        "moments 非空时忽略 count。使用 PyAV 提取视频帧。"
    ).classes("text-xs text-gray-600 font-mono mb-1")
    ss_str = json.dumps(
        cfg.get("screenshot_config", {"count": 3, "moments": []}),
        ensure_ascii=False, indent=2,
    )
    ss_editor = (
        ui.textarea(value=ss_str)
        .classes("w-full bg-gray-700 text-yellow-100 font-mono text-sm")
        .style("min-height: 80px;")
    )

    # 扩展配置（JSON）
    ui.label("扩展配置 (Extra Config):").classes(
        "text-sm font-mono text-gray-400 mt-4 mb-2"
    )
    extra_str = json.dumps(cfg.get("extra_config", {}), ensure_ascii=False, indent=2)
    extra_editor = (
        ui.textarea(value=extra_str)
        .classes("w-full bg-gray-700 text-yellow-100 font-mono text-sm")
        .style("min-height: 80px;")
    )

    # 操作按钮行
    with ui.row().classes("gap-4 mt-6"):
        save_btn = ui.button(
            "◆ 保存配置",
            on_click=lambda: _save_config(
                config_mgr, profile, root_input.value,
                from_input.value, to_input.value,
                rules_editor.value, schema_editor.value,
                ss_editor.value, extra_editor.value,
                status_label,
            ),
        )
        save_btn.classes(
            "bg-cyan-900 hover:bg-cyan-700 text-cyan-300 font-mono "
            "border border-cyan-600 rounded px-6 py-2"
        )

        # 重置按钮
        reset_btn = ui.button("◇ 重置", on_click=lambda: switch_page("config"))
        reset_btn.classes(
            "bg-gray-800 hover:bg-gray-700 text-gray-400 font-mono "
            "border border-gray-600 rounded px-6 py-2"
        )

    # 状态提示
    status_label = ui.label("").classes("text-sm font-mono mt-4")


def _on_profile_switch(new_profile: str, config_mgr):
    """Profile 切换回调。

    触发时机：用户在下拉框中选择了新的 Profile。
    执行流程：
        1. 更新 config_mgr.current_profile
        2. 刷新左侧抽屉显示
        3. 刷新整个页面（重新渲染配置页）

    Args:
        new_profile: 新 Profile 名称
        config_mgr: ConfigManager 实例
    """
    config_mgr.current_profile = new_profile
    update_drawer_info()
    switch_page("config")


def _save_config(config_mgr, profile, root, from_path, to_path, rules_str, schema_str, ss_str, extra_str, status_label):
    """保存配置回调。

    触发时机：用户点击"保存配置"按钮。

    Args:
        config_mgr: ConfigManager 实例
        profile: 当前 Profile 名称
        root: Root 路径（已整理视频目录，DB 同步扫描此目录）
        from_path: From 路径（原始新视频目录）
        to_path: To 路径（更名后目标目录）
        rules_str: 命名规则 JSON 字符串
        schema_str: 表结构 JSON 字符串
        ss_str: 截图配置 JSON 字符串
        extra_str: 扩展配置 JSON 字符串
        status_label: 状态提示 UI 元素
    """
    try:
        naming_rules = json.loads(rules_str) if rules_str.strip() else {}
    except json.JSONDecodeError as e:
        status_label.set_text(f"命名规则 JSON 格式错误: {e}")
        status_label.classes("text-red-400 text-sm font-mono mt-4")
        return

    try:
        table_schema = json.loads(schema_str) if schema_str.strip() else []
        if not isinstance(table_schema, list):
            raise ValueError("表结构必须是数组")
        for col in table_schema:
            if "name" not in col:
                raise ValueError(f"表结构列缺少 name: {col}")
    except (json.JSONDecodeError, ValueError) as e:
        status_label.set_text(f"表结构 JSON 格式错误: {e}")
        status_label.classes("text-red-400 text-sm font-mono mt-4")
        return

    try:
        ss_config = json.loads(ss_str) if ss_str.strip() else {"count": 3, "moments": []}
    except json.JSONDecodeError as e:
        status_label.set_text(f"截图配置 JSON 格式错误: {e}")
        status_label.classes("text-red-400 text-sm font-mono mt-4")
        return

    try:
        extra_config = json.loads(extra_str) if extra_str.strip() else {}
    except json.JSONDecodeError as e:
        status_label.set_text(f"扩展配置 JSON 格式错误: {e}")
        status_label.classes("text-red-400 text-sm font-mono mt-4")
        return

    try:
        config_mgr.update_profile_config(profile, "root", root)
        config_mgr.update_profile_config(profile, "from", from_path)
        config_mgr.update_profile_config(profile, "to", to_path)
        config_mgr.update_profile_config(profile, "naming_rules", naming_rules)
        config_mgr.update_profile_config(profile, "table_schema", table_schema)
        config_mgr.update_profile_config(profile, "screenshot_config", ss_config)
        config_mgr.update_profile_config(profile, "extra_config", extra_config)
        update_drawer_info()
        status_label.set_text("配置已保存 ✓")
        status_label.classes("text-green-400 text-sm font-mono mt-4")
    except Exception as e:
        status_label.set_text(f"保存失败: {e}")
        status_label.classes("text-red-400 text-sm font-mono mt-4")

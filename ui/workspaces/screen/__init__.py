"""影视业务前端 — 专用页面与概览扩展注册。"""

# 专用页面注册：page key → (图标, 标签, "module:builder")。
# 菜单键顺序由 workspaces/__init__.py 的 WORKSPACES["screen"]["menu"] 决定。
PAGES = {
    "scan": ("▤", "扫描", "ui.workspaces.screen.scan:build_scan"),
    "normalize": ("✎", "标准化", "ui.workspaces.screen.normalize:build_normalize"),
    "screenshot": ("▣", "截图", "ui.workspaces.screen.screenshot:build_screenshot"),
    "kb": ("▥", "知识库", "ui.workspaces.screen.knowledge_base:build_kb"),
    "sub_download": ("◉", "字幕", "ui.workspaces.screen.subtitle:build_subtitle"),
}


def register():
    """注册概览页扩展（DeepSeek Key 卡片）。由 ui.state._register_workspace_pages 调用。"""
    from ui.home import register_overview_extra
    from ui.workspaces.screen.overview import build_deepseek_card
    register_overview_extra(build_deepseek_card)

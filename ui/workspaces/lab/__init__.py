"""练习业务前端 — 专用页面注册。

一个功能一页，菜单键顺序由 workspaces/__init__.py 的 WORKSPACES["lab"]["menu"] 决定。
"""

PAGES = {
    "dts": ("◉", "DTS 检测", "ui.workspaces.lab.dts:build_dts"),
    "subtitle": ("▣", "字幕提取", "ui.workspaces.lab.subtitle:build_subtitle"),
}

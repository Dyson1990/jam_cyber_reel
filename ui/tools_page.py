"""
工具页模块 - 脚本展示与运行。

文件作用：
    列出 tools/ 目录下的脚本，查看源码、运行脚本、复制运行结果。

与其它模块的关系：
    - 被 ui/state.py 的 switch_page("tools") 调用
    - 脚本扫描/运行委托 core/common/tools.py

主要函数：
    build_tools(config_mgr, db) - 构建工具页 UI
"""

from nicegui import run, ui

from core.common.tools import list_scripts, run_script
from ui.state import tag


def build_tools(config_mgr, db):
    """构建工具页 UI。

    布局：左侧脚本列表，右侧源码 + 运行结果。

    Args:
        config_mgr: ConfigManager 实例
        db: Database 实例
    """
    scripts = list_scripts()

    tag("tools")
    ui.label("◆ TOOLS").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")

    if not scripts:
        ui.label("tools/ 目录下暂无脚本").classes("text-gray-500 font-mono")
        return

    with ui.row().classes("w-full gap-4"):
        # 左侧：脚本列表
        with ui.column().classes("gap-2").style("width: 200px;"):
            tag("script-list")
            ui.label("脚本列表").classes("text-xs text-gray-500 font-mono mb-2")
            selected_script = {"path": scripts[0]}  # 用 dict 保存可变引用

            for script in scripts:
                name = script.stem
                btn = ui.button(
                    name,
                    on_click=lambda _, s=script: _select_script(
                        s, selected_script, source_area, args_input, output_area
                    ),
                )
                btn.classes(
                    "w-full text-left bg-gray-900 hover:bg-cyan-900 text-cyan-300 "
                    "border border-cyan-800 rounded font-mono text-xs py-1 px-3"
                )
                btn.style("justify-content: flex-start;")

        # 右侧：源码 + 参数 + 运行结果
        with ui.column().classes("flex-1 gap-3"):
            # 全局注入：工具页 textarea/input 黑底白字
            ui.add_head_html("""
            <style>
                .tools-dark-textarea .q-field__native,
                .tools-dark-textarea textarea,
                .tools-dark-input .q-field__native,
                .tools-dark-input input {
                    background: #000 !important;
                    color: #ddd !important;
                }
                .tools-dark-textarea .q-field__control,
                .tools-dark-input .q-field__control {
                    background: #000 !important;
                    border-color: #333 !important;
                }
            </style>
            """)

            # 源码区
            tag("script-source")
            ui.label("源码").classes("text-xs text-gray-500 font-mono")
            source_area = (
                ui.textarea(value="")
                .classes("w-full font-mono text-xs tools-dark-textarea")
                .props("readonly autogrow outlined dense")
            )

            # 参数区
            tag("script-args")
            ui.label("参数（留空则使用 Profile 的 root 路径）").classes("text-xs text-gray-500 font-mono")
            args_input = (
                ui.input(value="", placeholder="路径或参数，空格分隔")
                .classes("w-full font-mono text-xs tools-dark-input")
                .props("outlined dense")
            )

            # 按钮行
            with ui.row().classes("gap-4"):
                tag("script-actions")
                run_btn = ui.button(
                    "▶ 运行",
                    on_click=lambda: _run_script(
                        selected_script["path"], config_mgr, args_input, output_area
                    ),
                )
                run_btn.classes(
                    "bg-cyan-900 hover:bg-cyan-700 text-cyan-300 font-mono "
                    "border border-cyan-600 rounded px-4 py-1 text-sm"
                )

                copy_btn = ui.button(
                    "📋 复制结果",
                    on_click=lambda: _copy_output(output_area),
                )
                copy_btn.classes(
                    "bg-gray-800 hover:bg-gray-700 text-gray-300 font-mono "
                    "border border-gray-600 rounded px-4 py-1 text-sm"
                )

            # 运行结果区
            tag("script-output")
            ui.label("运行结果").classes("text-xs text-gray-500 font-mono mt-2")
            output_area = (
                ui.textarea(value="")
                .classes("w-full font-mono text-xs tools-dark-textarea")
                .props("readonly autogrow outlined dense")
            )

    # 默认加载第一个脚本
    if scripts:
        _select_script(scripts[0], selected_script, source_area, args_input, output_area)


def _select_script(script_path, selected, source_area, args_input, output_area):
    """选择脚本：加载源码并清空参数和结果区。"""
    selected["path"] = script_path
    try:
        source = script_path.read_text(encoding="utf-8")
    except Exception as e:
        source = f"无法读取源码: {e}"
    source_area.set_value(source)
    args_input.set_value("")
    output_area.set_value("")


async def _run_script(script_path, config_mgr, args_input, output_area):
    """运行选中的脚本（后台线程，避免阻塞事件循环）。"""
    output_area.set_value("运行中...")
    result = await run.io_bound(run_script, script_path, config_mgr, args_input.value)
    output_area.set_value(result)


async def _copy_output(output_area):
    """将运行结果复制到剪贴板。"""
    text = output_area.value
    if text:
        await ui.clipboard.write(text)
        ui.notify("结果已复制到剪贴板", type="positive")
    else:
        ui.notify("无内容可复制", type="warning")

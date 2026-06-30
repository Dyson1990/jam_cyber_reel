"""
工具页模块 - 脚本展示与运行。

文件作用：
    列出 tools/ 目录下的脚本，查看源码、运行脚本、复制运行结果。

与其它模块的关系：
    - 被 ui/state.py 的 switch_page("tools") 调用
    - 通过 subprocess 运行脚本
    - 使用 config_mgr 获取当前 Profile 的 root 作为默认参数

主要函数：
    build_tools(config_mgr, db) - 构建工具页 UI
"""

import os
import subprocess
import sys
from pathlib import Path

from nicegui import ui

# 项目根目录
_PROJECT_ROOT = Path(__file__).parent.parent
_TOOLS_DIR = _PROJECT_ROOT / "tools"


def _list_scripts() -> list[Path]:
    """扫描 tools/ 目录，返回所有 .py 脚本路径。"""
    if not _TOOLS_DIR.exists():
        return []
    return sorted(
        f for f in _TOOLS_DIR.iterdir()
        if f.suffix == ".py" and not f.name.startswith("_")
    )


def build_tools(config_mgr, db):
    """构建工具页 UI。

    布局：左侧脚本列表，右侧源码 + 运行结果。

    Args:
        config_mgr: ConfigManager 实例
        db: Database 实例
    """
    scripts = _list_scripts()

    ui.label("◆ TOOLS").classes("text-xl font-mono text-cyan-400 mb-6 glow-text")

    if not scripts:
        ui.label("tools/ 目录下暂无脚本").classes("text-gray-500 font-mono")
        return

    with ui.row().classes("w-full gap-4"):
        # 左侧：脚本列表
        with ui.column().classes("gap-2").style("width: 200px;"):
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
            ui.label("源码").classes("text-xs text-gray-500 font-mono")
            source_area = (
                ui.textarea(value="")
                .classes("w-full font-mono text-xs tools-dark-textarea")
                .props("readonly autogrow outlined dense")
            )

            # 参数区
            ui.label("参数（留空则使用 Profile 的 root 路径）").classes("text-xs text-gray-500 font-mono")
            args_input = (
                ui.input(value="", placeholder="路径或参数，空格分隔")
                .classes("w-full font-mono text-xs tools-dark-input")
                .props("outlined dense")
            )

            # 按钮行
            with ui.row().classes("gap-4"):
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


def _run_script(script_path, config_mgr, args_input, output_area):
    """运行选中的脚本。

    若参数区非空则用参数区内容作为 argv[1:]（空格分隔），
    否则用当前 Profile 的 root 作为默认参数。
    """
    output_area.set_value("运行中...")

    user_args = args_input.value.strip()
    if user_args:
        cmd = [sys.executable, str(script_path)] + user_args.split()
    else:
        root = config_mgr.get_profile_root() or str(Path.cwd())
        cmd = [sys.executable, str(script_path), root]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(_PROJECT_ROOT),
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if not output.strip():
            output = "(无输出)"
        output_area.set_value(output)
    except subprocess.TimeoutExpired:
        output_area.set_value("运行超时（30秒）")
    except Exception as e:
        output_area.set_value(f"运行失败: {e}")


async def _copy_output(output_area):
    """将运行结果复制到剪贴板。"""
    text = output_area.value
    if text:
        await ui.clipboard.write(text)
        ui.notify("结果已复制到剪贴板", type="positive")
    else:
        ui.notify("无内容可复制", type="warning")

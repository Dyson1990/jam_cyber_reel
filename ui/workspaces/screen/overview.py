"""screen 概览扩展 — DeepSeek Key 卡片（全站统一入口，仅 screen 展示）。"""

from nicegui import ui

from ui.state import tag
from workspaces.screen.overview import get_deepseek_key, set_deepseek_key


def build_deepseek_card(config_mgr, db, profile):
    """在概览页追加 DeepSeek Key 卡片（输入即保存，脱敏显示）。"""
    with ui.card().classes("bg-slate-950 border border-cyan-800 rounded-lg p-4 w-full mt-4"):
        tag("deepseek-key")
        ui.label("DeepSeek Key（全站统一）").classes("text-xs text-slate-500 font-mono")
        key = get_deepseek_key(config_mgr)
        key_input = ui.input(
            value=_mask_secret(key) if key else "",
            placeholder="未设置（输入新 Key 保存）" if not key else "输入新 Key 覆盖",
        ).props("outlined dense dark").classes("w-full font-mono text-xs mt-2")
        key_input.on_value_change(
            lambda e: _save_deepseek_key(config_mgr, e.value or "", key_input),
        )


def _mask_secret(key: str) -> str:
    """脱敏显示 key：仅保留前 3 后 4 位。"""
    if not key:
        return "未设置"
    if len(key) <= 7:
        return "*******"
    return f"{key[:3]}****{key[-4:]}"


def _save_deepseek_key(config_mgr, value, key_input):
    """录入新 key：非空才覆盖保存，并刷新为脱敏显示。"""
    if value:
        set_deepseek_key(config_mgr, value)
        key_input.set_value(_mask_secret(value))

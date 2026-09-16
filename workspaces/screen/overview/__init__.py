"""概览（screen）— DeepSeek Key 管理（全站统一，仅 screen 展示）。"""
from workspaces.screen.config import DEEPSEEK_KEY


def get_deepseek_key(config_mgr) -> str:
    """screen 统一读取 DeepSeek Key（唯一来源：workspace 共享配置）。"""
    return config_mgr.get_shared("screen", DEEPSEEK_KEY, "") or ""


def set_deepseek_key(config_mgr, value: str) -> None:
    """screen 统一写入 DeepSeek Key。"""
    config_mgr.set_shared("screen", DEEPSEEK_KEY, value)

"""影视业务 — 通用配置（movie / tv 共享的 from/to/root 等跨功能参数）。

功能页专属参数（如 ai_prompt、screenshot_config）分散在各自后端文件夹的 defaults.py，
此处只保留跨功能共享的通用项，本文件作为 schema 单一来源。
"""

from workspaces.screen.normalize.defaults import DEFAULTS as _NORMALIZE
from workspaces.screen.screenshot.defaults import DEFAULTS as _SCREENSHOT
from workspaces.screen.subtitle.defaults import DEFAULTS as _SUBTITLE

_COMMON = {
    "root": "",
    "from": "",
    "to": "",
    "extra_config": {},
    **_NORMALIZE,
    **_SCREENSHOT,
    **_SUBTITLE,
}

PROFILES = {
    "movie": {
        **_COMMON,
        "name": "电影",
        "table_schema": [
            {"name": "director", "type": "TEXT", "label": "导演"},
            {"name": "year", "type": "INTEGER", "label": "年份"},
            {"name": "file_size", "type": "INTEGER", "label": "文件大小"},
            {"name": "duration", "type": "REAL", "label": "时长"},
            {"name": "codec", "type": "TEXT", "label": "编码"},
            {"name": "resolution", "type": "TEXT", "label": "分辨率"},
        ],
    },
    "tv": {
        **_COMMON,
        "name": "电视剧",
        "table_schema": [
            {"name": "series", "type": "TEXT", "label": "系列"},
            {"name": "year", "type": "INTEGER", "label": "年份"},
            {"name": "file_size", "type": "INTEGER", "label": "文件大小"},
            {"name": "duration", "type": "REAL", "label": "时长"},
            {"name": "codec", "type": "TEXT", "label": "编码"},
            {"name": "resolution", "type": "TEXT", "label": "分辨率"},
        ],
    },
}


# ==================== DeepSeek Key 共享配置 ====================

DEEPSEEK_KEY = "deepseek_key"

# 已废弃的旧键：从运行时配置中清除，避免残留在 overrides.json 中。
_LEGACY_KEYS = ("ai_api_key", "crid_pattern", "kb_path", "ai_fix_path", "ai_year")


def migrate_shared(profiles: dict, shared: dict) -> None:
    """迁移：旧 per-profile ai_api_key → screen 共享 deepseek_key，并清除废弃键。"""
    sh = shared.setdefault("screen", {})
    for p in PROFILES:
        cfg = profiles.get(p, {})
        legacy = cfg.pop("ai_api_key", "")
        if legacy and not sh.get(DEEPSEEK_KEY):
            sh[DEEPSEEK_KEY] = legacy
        for k in _LEGACY_KEYS:
            cfg.pop(k, None)

"""影视业务 — 默认 Profile 配置（movie / tv）。"""

PROFILES = {
    "movie": {
        "name": "电影",
        "root": "",
        "from": "",
        "to": "",
        "naming_rules": {},
        "extra_config": {},
        "crid_pattern": "",
        "naming_mode": "mapping",
        "ai_prompt": "",
        "ai_batch_size": 20,
        "ai_douban": False,
        "tmdb_api_key": "",
        "ai_fix_path": "",
        "kb_path": "",
        "screenshot_config": {"count": 3, "moments": []},
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
        "name": "电视剧",
        "root": "",
        "from": "",
        "to": "",
        "naming_rules": {},
        "extra_config": {},
        "crid_pattern": "",
        "naming_mode": "mapping",
        "ai_prompt": "",
        "ai_batch_size": 20,
        "ai_douban": False,
        "tmdb_api_key": "",
        "ai_fix_path": "",
        "kb_path": "",
        "screenshot_config": {"count": 3, "moments": []},
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


def migrate_shared(profiles: dict, shared: dict) -> None:
    """迁移：旧的 per-profile ai_api_key → screen 共享 deepseek_key。"""
    sh = shared.setdefault("screen", {})
    for p in PROFILES:
        legacy = profiles.get(p, {}).pop("ai_api_key", "")
        if legacy and not sh.get(DEEPSEEK_KEY):
            sh[DEEPSEEK_KEY] = legacy

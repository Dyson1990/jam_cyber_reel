"""标准化（screen）功能参数默认值。

独立模块，仅存数据、不 import ai_naming，避免 schema.py 在启动时拖入 LangChain。
"""

DEFAULTS = {
    "naming_mode": "mapping",   # "mapping"（映射命名）| "ai"（AI 命名）| "ai_fix"（AI 修正）
    "naming_rules": {},
    "ai_prompt": "",
    "ai_prompt_updated": "",
    "ai_batch_size": 20,
    "ai_douban": False,
    "tmdb_api_key": "",
}

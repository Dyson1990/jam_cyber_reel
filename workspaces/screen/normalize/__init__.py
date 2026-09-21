"""标准化（screen）— AI 命名/修正后端（LangChain + DeepSeek）。"""
from .ai_naming import (
    build_prompt, build_tv_prompt, build_fix_prompt, call_deepseek, extract_names,
    tv_summarizable,
)

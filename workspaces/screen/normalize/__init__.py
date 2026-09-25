"""标准化（screen）— AI 槽位补全（ai_slots）+ 文件名拼装（naming）。"""
from .ai_slots import (
    build_prompt, build_tv_prompt, build_fix_prompt, call_deepseek, extract_names,
    tv_summarizable,
)
from .naming import assemble, assemble_fix

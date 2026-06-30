"""
Homework Profile - 命名规则（regex 方式）。

设计理由：
    Homework 类媒体（如学习视频）通常使用课程编号-标题格式，
    regex 比 dict 映射更适合这种有规律但不固定的命名模式。

    预留接口，用户可通过 UI 配置自定义 regex pattern。
"""

# 默认正则模式 —— 预留接口
# 格式：(正则表达式, 替换模板)
# handler 使用 re.sub(pattern, replacement, filename)
DEFAULT_PATTERN: str = r"^(.*?)[\-_\.\s]+(.*)$"

# pattern 中的分组说明：
#   \1 - 课程编号或标识
#   \2 - 标题或描述
# 替换模板示例：r"\1 - \2" 可将 "CS101_Intro.mp4" → "CS101 - Intro.mp4"
DEFAULT_REPLACEMENT: str = r"\1 - \2"

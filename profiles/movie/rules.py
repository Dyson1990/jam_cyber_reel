"""
电影 Profile - 命名规则（dict 映射方式）。

文件作用：
    定义电影文件名的规范化规则。
    采用 dict 映射方式：{匹配模式: 替换模板}。

设计理由：
    规则与逻辑分离 —— rules.py 仅定义规则数据，
    handler.py 负责应用规则，便于用户自定义规则而不触及核心逻辑。
    预留接口，不硬编码大量数据。
"""

# 命名映射规则 —— 预留接口
# 格式：{关键词/模式: 标准名称}
# handler.py 会遍历此字典，匹配文件名并替换
NAME_MAP: dict[str, str] = {
    # 示例规则（用户可在配置页面扩展）：
    # "4k": "2160p",
    # "hdr": "HDR",
    # "extended": "EXTENDED",
}

# 分隔符替换映射
SEPARATOR_MAP: dict[str, str] = {
    ".": " ",
    "_": " ",
}

# 年份提取正则（预留，handler 中使用）
YEAR_PATTERN: str = r"(19|20)\d{2}"

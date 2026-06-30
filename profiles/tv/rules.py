"""
电视剧 Profile - 命名规则（dict 映射方式）。

文件作用：
    定义电视剧文件名的规范化规则。
    格式：{匹配模式: 替换模板}。

设计理由：
    与 Movie/RealShot 使用相同的 dict 映射机制，
    仅映射数据不同。预留接口，不硬编码大量数据。
"""

# 命名映射规则 —— 预留接口
NAME_MAP: dict[str, str] = {
    # 示例：可配置剧集名缩写 → 全称映射
    # "S01": "Season01",
    # "EP": "E",
}

SEPARATOR_MAP: dict[str, str] = {
    ".": " ",
    "_": " ",
}

YEAR_PATTERN: str = r"(19|20)\d{2}"

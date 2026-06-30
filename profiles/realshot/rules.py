"""
实拍 Profile - 命名规则（dict 映射方式）。

设计理由：
    实拍类媒体通常以日期/设备命名，预留设备名→标准名映射接口。
"""

NAME_MAP: dict[str, str] = {
    # 示例：设备缩写 → 全称
    # "dji": "DJI",
    # "gopro": "GoPro",
}

SEPARATOR_MAP: dict[str, str] = {
    ".": " ",
    "_": " ",
}

YEAR_PATTERN: str = r"(19|20)\d{2}"

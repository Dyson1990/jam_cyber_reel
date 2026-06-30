"""
电视剧 Profile - 继承 ProfileBase 默认 normalize()（dict 映射方式）。
"""

from profiles import ProfileBase


class TVHandler(ProfileBase):
    """电视剧媒体处理器 —— naming_rules dict 映射更名。"""

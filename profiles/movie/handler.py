"""
电影 Profile - 继承 ProfileBase 默认 normalize()（dict 映射方式）。
"""

from profiles import ProfileBase


class MovieHandler(ProfileBase):
    """电影媒体处理器 —— naming_rules dict 映射更名。"""

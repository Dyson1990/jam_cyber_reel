"""
电影 Profile - 配置定义。

文件作用：
    定义电影类型媒体的默认配置，包括支持的视频扩展名、
    默认 root 和 target 路径等静态配置项。

运行时配置（root、naming_rules 等）
由 config_manager 管理，此文件仅提供 Profile 元信息。
"""

PROFILE_KEY = "movie"
PROFILE_NAME = "电影"
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".ts"}
DEFAULT_ROOT = ""

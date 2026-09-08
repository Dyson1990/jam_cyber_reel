"""
练习业务（lab）— homework Profile 插件。

区别于 movie/tv/realshot 的默认 dict 字符串替换，homework 使用 regex 规范化文件名，
并额外从文件名提取课程编号作为 series 列。

通过继承 ProfileBase 并声明 profile_name="homework" 注册为插件，
由 ProfileRegistry.discover() 自动加载；其余 profile 无自定义逻辑，回退默认 ProfileBase。
"""

import re
from pathlib import Path

from core.files import VIDEO_EXTENSIONS
from workspaces._shared import ProfileBase


class HomeworkHandler(ProfileBase):
    """Homework 媒体处理器 —— regex 替换规范化文件名 + 提取课程编号。"""

    profile_name = "homework"

    def normalize(self, files: list[Path]) -> dict[Path, str]:
        naming_rules = self.config.get("naming_rules", {})
        pattern = naming_rules.get("pattern", "")
        replacement = naming_rules.get("replacement", "")

        result: dict[Path, str] = {}
        for f in files:
            stem = f.stem
            if pattern and replacement:
                try:
                    stem = re.sub(pattern, replacement, stem)
                except re.error:
                    pass
            stem = re.sub(r"\s+", " ", stem).strip()
            result[f] = f"{stem}{f.suffix}"
        return result

    def build_db(self) -> int:
        """重写 build_db，Homework 额外尝试提取课程编号作为 series。"""
        root = self.config.get("root", "")
        if not root:
            return 0

        scan_path = Path(root)
        if not scan_path.exists():
            return 0

        naming_rules = self.config.get("naming_rules", {})
        pattern = naming_rules.get("pattern", "")

        count = 0
        for f in scan_path.iterdir():
            if not f.is_file() or f.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            series = ""
            if pattern:
                try:
                    m = re.match(pattern, f.stem)
                    if m and m.lastindex and m.lastindex >= 1:
                        series = m.group(1)
                except re.error:
                    pass
            self.db.upsert_media(
                profile=self.profile_name,
                title=f.stem,
                mv_path=str(f),
                series=series,
                file_size=f.stat().st_size,
            )
            count += 1
        return count

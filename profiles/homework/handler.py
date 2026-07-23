"""
Homework Profile - regex 方式 normalize()。

与 Movie/TV/RealShot 不同，Homework 使用正则表达式进行文件名规范化。
naming_rules 格式：{"pattern": "...", "replacement": "..."}
"""

import re
from pathlib import Path

from profiles import ProfileBase
from core.files import VIDEO_EXTENSIONS


class HomeworkHandler(ProfileBase):
    """Homework 媒体处理器 —— regex 替换规范化文件名。

    naming_rules 中 pattern/replacement 为空时保留原名。
    """

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

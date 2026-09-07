"""
Profile 插件架构 — ProfileBase 基类 + ProfileRegistry 注册中心。

实现委托到 core/ 模块：
    core/db.py          — Database 封装
    core/files.py       — 文件扫描、重命名、回滚
    core/screenshots.py — 截图采集（PyAV）
    core/sync.py        — 数据库同步
"""

import importlib
from pathlib import Path
from typing import Optional

from core.files import rename_files, rollback_records as _rollback_records, scan_videos, VIDEO_EXTENSIONS
from core.sync import build_db as _build_db, diff_db as _diff_db, sync_db as _sync_db


class ProfileBase:
    """所有 Profile handler 的基类。

    通用实现委托到 core/ 模块，子类只需实现 normalize()。
    """

    def __init__(self, db, config_manager):
        self.db = db
        self.config_manager = config_manager
        self.profile_name: str = self.__class__.__module__.split(".")[-2]

    @property
    def config(self) -> dict:
        return self.config_manager.get_profile_config(self.profile_name)

    # === scan ===

    def scan(
        self,
        root_override: Optional[Path] = None,
        exclude_dirs: Optional[list[str]] = None,
    ) -> list[Path]:
        root = root_override or Path(self.config.get("root", ""))
        return scan_videos(root, exclude_dirs=exclude_dirs)

    # === normalize ===

    def normalize(self, files: list[Path]) -> dict[Path, str]:
        """默认 dict 映射替换。子类可 override。"""
        rules = self.config.get("naming_rules", {})
        return {f: _apply_rules(f.name, rules) for f in files}

    # === rename ===

    def rename(
        self, mapping: dict[Path, str], target_dir: Optional[Path] = None
    ) -> list[dict]:
        return rename_files(mapping, target_dir, self.db, self.profile_name)

    # === rollback ===

    def rollback_records(
        self, records: list, source_dir: Optional[Path] = None
    ) -> list[dict]:
        return _rollback_records(records, self.db, source_dir=source_dir)

    def rollback_last_batch(self, source_dir: Optional[Path] = None) -> list[dict]:
        batch = self.db.get_last_batch(self.profile_name)
        if not batch:
            return [{"status": "无历史记录可回滚"}]
        return self.rollback_records(batch, source_dir=source_dir)

    def rollback_date_range(
        self, start_date: str, end_date: str, source_dir: Optional[Path] = None
    ) -> list[dict]:
        batch = self.db.get_rename_by_date_range(
            self.profile_name, start_date, end_date
        )
        if not batch:
            return [{"status": "日期范围内无记录"}]
        return self.rollback_records(batch, source_dir=source_dir)

    # === db sync ===

    def build_db(self) -> int:
        return _build_db(self.config.get("root", ""), self.db, self.profile_name)

    def diff_db(self, exclude_dirs: Optional[list[str]] = None) -> dict:
        return _diff_db(
            self.config.get("root", ""), self.db, self.profile_name,
            exclude_dirs=exclude_dirs,
        )

    def sync_db(
        self, exclude_dirs: Optional[list[str]] = None, crid_pattern: str = "",
    ) -> int:
        return _sync_db(
            self.config.get("root", ""), self.db, self.profile_name,
            exclude_dirs=exclude_dirs, crid_pattern=crid_pattern,
        )


def _apply_rules(name: str, rules: dict) -> str:
    for key, val in rules.items():
        name = name.replace(key, val)
    return name


class ProfileRegistry:
    """Profile 注册中心 — 自动扫描 profiles/ 目录发现 handler。"""

    def __init__(self, profiles_path: Path, db, config_manager):
        self.profiles_path = profiles_path
        self.db = db
        self.config_manager = config_manager
        self._handlers: dict[str, ProfileBase] = {}

    def discover(self) -> dict[str, ProfileBase]:
        self._handlers.clear()
        for item in self.profiles_path.iterdir():
            if not item.is_dir() or item.name.startswith("_"):
                continue
            try:
                mod = importlib.import_module(f"profiles.{item.name}.handler")
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, ProfileBase)
                        and attr is not ProfileBase
                    ):
                        self._handlers[item.name] = attr(self.db, self.config_manager)
                        break
            except Exception as e:
                print(f"[Registry] {item.name} 加载失败: {e}")
        return self._handlers

    def get(self, name: str) -> Optional[ProfileBase]:
        return self._handlers.get(name)

    def list_names(self) -> list[str]:
        return list(self._handlers.keys())

    @property
    def handler_count(self) -> int:
        return len(self._handlers)

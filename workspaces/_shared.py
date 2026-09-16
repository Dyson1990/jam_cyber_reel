"""Workspaces 共享后端 — 配置校验保存 + Profile 插件框架。

配置部分（screen/lab 复用）：
    parse_naming_rules / parse_table_schema / parse_json_or / save_config

Profile 插件框架：
    ProfileBase     — 所有 Profile handler 基类，通用逻辑委托 core/，子类按需 override
    ProfileRegistry — 注册中心，扫描各 workspace 的 profile.py 发现自定义 handler，
                      无自定义逻辑的 profile 回退默认 ProfileBase（dict 映射）
    _apply_rules    — 默认命名规则（dict 字符串替换）

插件扩展方式：在对应 workspace 目录下新建 profile.py，定义继承 ProfileBase 的类并声明
profile_name（= profile key）。见 workspaces/lab/profile.py 的 HomeworkHandler。
"""

import importlib
import json
from pathlib import Path
from typing import Optional

from core.files import (
    rename_files,
    rollback_records as _rollback_records,
    scan_videos,
    VIDEO_EXTENSIONS,
)
from workspaces import workspace_of


# ==================== 配置校验与保存 ====================


def parse_naming_rules(s: str) -> dict:
    return json.loads(s) if s.strip() else {}


def parse_table_schema(s: str) -> list:
    if not s.strip():
        return []
    data = json.loads(s)
    if not isinstance(data, list):
        raise ValueError("表结构必须是数组")
    for col in data:
        if "name" not in col:
            raise ValueError(f"表结构列缺少 name: {col}")
    return data


def parse_json_or(s: str, default):
    return json.loads(s) if s.strip() else default


def save_config(
    config_mgr, profile: str, root: str, from_path: str, to_path: str,
    rules_str: str, schema_str: str, ss_str: str, extra_str: str,
) -> str:
    """校验并保存 Profile 配置，返回错误信息（空串表示成功）。"""
    try:
        naming_rules = parse_naming_rules(rules_str)
    except json.JSONDecodeError as e:
        return f"命名规则 JSON 格式错误: {e}"
    try:
        table_schema = parse_table_schema(schema_str)
    except (json.JSONDecodeError, ValueError) as e:
        return f"表结构 JSON 格式错误: {e}"
    try:
        ss_config = parse_json_or(ss_str, {"count": 3, "moments": []})
    except json.JSONDecodeError as e:
        return f"截图配置 JSON 格式错误: {e}"
    try:
        extra_config = parse_json_or(extra_str, {})
    except json.JSONDecodeError as e:
        return f"扩展配置 JSON 格式错误: {e}"

    config_mgr.update_profile_config(profile, "root", root)
    config_mgr.update_profile_config(profile, "from", from_path)
    config_mgr.update_profile_config(profile, "to", to_path)
    config_mgr.update_profile_config(profile, "naming_rules", naming_rules)
    config_mgr.update_profile_config(profile, "table_schema", table_schema)
    config_mgr.update_profile_config(profile, "screenshot_config", ss_config)
    config_mgr.update_profile_config(profile, "extra_config", extra_config)
    return ""


# ==================== Profile 插件框架 ====================


class ProfileBase:
    """所有 Profile handler 的基类。

    通用实现委托 core/ 模块；子类声明 profile_name 并按需 override
    normalize() / build_db() 等以注入业务特有逻辑。
    """

    profile_name = ""  # 子类覆盖：声明该 handler 对应的 profile key

    def __init__(self, db, config_manager):
        self.db = db
        self.config_manager = config_manager

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


def _apply_rules(name: str, rules: dict) -> str:
    for key, val in rules.items():
        name = name.replace(key, val)
    return name


class ProfileRegistry:
    """Profile 注册中心 — 扫描各 workspace 的 profile.py 发现自定义 handler。

    发现规则：对 config_manager 列出的每个 profile，按 workspace_of() 找到其 workspace，
    尝试 import `workspaces.<ws>.profile` 并匹配声明了同名 profile_name 的 ProfileBase 子类；
    未找到自定义 handler 时回退默认 ProfileBase（dict 映射）。
    """

    def __init__(self, db, config_manager):
        self.db = db
        self.config_manager = config_manager
        self._handlers: dict[str, ProfileBase] = {}

    def discover(self) -> dict[str, ProfileBase]:
        self._handlers.clear()
        for profile in self.config_manager.list_profiles():
            cls = self._find_handler(workspace_of(profile), profile) or ProfileBase
            h = cls(self.db, self.config_manager)
            h.profile_name = profile
            self._handlers[profile] = h
        return self._handlers

    def _find_handler(self, ws: str, profile: str) -> Optional[type]:
        try:
            mod = importlib.import_module(f"workspaces.{ws}.profile")
        except ModuleNotFoundError:
            return None
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, ProfileBase)
                and attr is not ProfileBase
                and getattr(attr, "profile_name", "") == profile
            ):
                return attr
        return None

    def get(self, name: str) -> Optional[ProfileBase]:
        return self._handlers.get(name)

    def list_names(self) -> list[str]:
        return list(self._handlers.keys())

    @property
    def handler_count(self) -> int:
        return len(self._handlers)

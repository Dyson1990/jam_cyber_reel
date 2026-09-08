"""
配置管理器 - 管理所有 Profile 的配置持久化。

文件作用：
    统一管理 Profile 配置的读写，使用 JSON 文件持久化。
    支持切换当前 Profile、修改配置、保存配置。

与其它模块的关系：
    - 被 UI 配置页调用（读取/修改/保存）
    - 被 Profile handler 调用（获取 root 等配置）
    - 被 main.py 初始化

主要类：
    ConfigManager: 配置管理核心类

数据流向：
    UI 配置页 → ConfigManager → profiles_config.json
    Profile handler ← ConfigManager.get_profile_config()
"""

import copy
import json
from pathlib import Path
from typing import Optional

from workspaces import PROFILE_DEFAULTS


class ConfigManager:
    """Profile 配置管理器。

    设计理由：
        所有配置集中管理，以 JSON 文件持久化，
        避免各 Profile 自行管理配置导致不一致。
        current_profile 也由此管理，确保全局唯一。
    """

    def __init__(self, config_path: Path):
        """初始化配置管理器。

        Args:
            config_path: 配置文件路径（profiles_config.json）
        """
        self.config_path = config_path
        self._data: dict = self._load()

    def _load(self) -> dict:
        """加载配置：默认结构为基底，磁盘存储的覆盖值合并其上。

        设计理由：
            默认 schema 由各 workspace 的 PROFILE_DEFAULTS 定义（单一来源），
            JSON 仅存用户运行时覆盖（root/from/to/naming_rules 等）。
            合并后，即使旧 JSON 缺失新字段（如 crid_pattern）也会被补齐。

        Returns:
            配置字典
        """
        data = self._default_config()
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self._merge_stored(data, json.load(f))
            except (json.JSONDecodeError, OSError):
                # 备份损坏文件，避免后续 save() 覆盖前丢失原配置
                try:
                    bak = self.config_path.with_name(self.config_path.name + ".bak")
                    bak.write_bytes(self.config_path.read_bytes())
                except OSError:
                    pass
        return data

    @staticmethod
    def _merge_stored(data: dict, stored: dict) -> None:
        """将存储值合并进默认结构：按 profile 浅合并，仅覆盖存储中出现的键。"""
        defaults = data["profiles"]
        for name, cfg in stored.get("profiles", {}).items():
            defaults.setdefault(name, {}).update(cfg)
        if "current_profile" in stored:
            data["current_profile"] = stored["current_profile"]

    def _default_config(self) -> dict:
        """生成默认配置结构（schema 来自各 workspace 的 PROFILE_DEFAULTS）。

        Returns:
            默认配置字典
        """
        return {
            "current_profile": "movie",
            "profiles": copy.deepcopy(PROFILE_DEFAULTS),
        }

    def save(self) -> None:
        """将当前配置写入磁盘。"""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    @property
    def current_profile(self) -> str:
        """获取当前激活的 Profile 名称。"""
        return self._data.get("current_profile", "movie")

    @current_profile.setter
    def current_profile(self, value: str) -> None:
        """切换当前 Profile。

        Args:
            value: Profile 名称（movie/tv/realshot/homework）
        """
        if value not in self._data.get("profiles", {}):
            raise ValueError(f"未知 Profile: {value}")
        self._data["current_profile"] = value
        self.save()

    def get_profile_config(self, profile: Optional[str] = None) -> dict:
        """获取指定 Profile 的配置。

        Args:
            profile: Profile 名称，默认使用当前 Profile

        Returns:
            配置字典（包含 name, root, naming_rules, extra_config）
        """
        if profile is None:
            profile = self.current_profile
        return self._data.get("profiles", {}).get(profile, {})

    def update_profile_config(self, profile: str, key: str, value) -> None:
        """更新指定 Profile 的单个配置项。

        Args:
            profile: Profile 名称
            key: 配置键名
            value: 新值
        """
        profiles = self._data.setdefault("profiles", {})
        p = profiles.setdefault(profile, {})
        p[key] = value
        self.save()

    def list_profiles(self) -> list[str]:
        """列出所有可用 Profile 名称。"""
        return list(self._data.get("profiles", {}).keys())

    def get_profile_root(self, profile: Optional[str] = None) -> str:
        """快捷获取 Profile 的 root 路径。"""
        cfg = self.get_profile_config(profile)
        return cfg.get("root", "")

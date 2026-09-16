"""
配置管理器 - 管理所有 Profile 的配置持久化。

文件作用：
    统一管理 Profile 配置的读写。
    各 Profile 的运行时覆盖值按业务域（workspace）分文件持久化，
    全局唯一的 current_profile 持久化到 core 状态文件。

与其它模块的关系：
    - 被 UI 配置页调用（读取/修改/保存）
    - 被 Profile handler 调用（获取 root 等配置）
    - 被 main.py 初始化

主要类：
    ConfigManager: 配置管理核心类

数据流向：
    UI 配置页 → ConfigManager → workspaces/<ws>/overrides.json（各 workspace 运行时覆盖）
    Profile handler ← ConfigManager.get_profile_config()
    current_profile → core/state.json（全局唯一）
"""

import copy
import importlib
import json
from pathlib import Path
from typing import Optional

from workspaces import PROFILE_DEFAULTS, WORKSPACES, workspace_of


class ConfigManager:
    """Profile 配置管理器。

    设计理由：
        默认 schema 由各 workspace 的 PROFILE_DEFAULTS 定义（单一来源），
        运行时覆盖值按 workspace 分文件持久化，避免集中式大 JSON 重复默认值。
        current_profile 全局唯一，独立持久化到 core/state.json。
    """

    def __init__(self, base: Path):
        """初始化配置管理器。

        Args:
            base: 项目根目录（workspaces/<ws>/overrides.json、core/state.json 位于其下）
        """
        self.base = base
        self._data: dict = self._load()

    def _load(self) -> dict:
        """加载配置：默认结构为基底，各 workspace 覆盖值 + core 状态合并其上。"""
        data = self._default_config()
        for ws in WORKSPACES:
            path = self._workspace_path(ws)
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        self._merge_stored(data, json.load(f))
                except (json.JSONDecodeError, OSError):
                    self._backup(path)
        state = self._state_path()
        if state.exists():
            try:
                with open(state, "r", encoding="utf-8") as f:
                    state_data = json.load(f)
                if state_data.get("current_profile"):
                    data["current_profile"] = state_data["current_profile"]
                sh = state_data.get("shared")
                if isinstance(sh, dict):
                    data.setdefault("shared", {}).update(sh)
            except (json.JSONDecodeError, OSError):
                pass
        self._run_shared_migrations(data)
        return data

    def _run_shared_migrations(self, data: dict) -> None:
        """调用各 workspace 声明的 migrate_shared(profiles, shared) 钩子。

        框架只按 WORKSPACES 键动态导入并调用钩子，不硬编码任何业务迁移逻辑。
        schema 模块名：screen 用 schema.py，其余 workspace 仍为 config.py（兼容）。
        """
        for ws in WORKSPACES:
            mod = None
            for name in ("schema", "config"):
                try:
                    mod = importlib.import_module(f"workspaces.{ws}.{name}")
                    break
                except ModuleNotFoundError:
                    continue
            migrate = getattr(mod, "migrate_shared", None) if mod else None
            if callable(migrate):
                migrate(data["profiles"], data.setdefault("shared", {}))

    def _workspace_path(self, ws: str) -> Path:
        return self.base / "workspaces" / ws / "overrides.json"

    def _state_path(self) -> Path:
        return self.base / "core" / "state.json"

    @staticmethod
    def _backup(path: Path) -> None:
        """损坏文件先备份，避免后续 save() 覆盖前丢失原值。"""
        try:
            path.with_name(path.name + ".bak").write_bytes(path.read_bytes())
        except OSError:
            pass

    @staticmethod
    def _merge_stored(data: dict, stored: dict) -> None:
        """按 profile 浅合并存储覆盖值到默认结构上。"""
        defaults = data["profiles"]
        for name, cfg in stored.get("profiles", {}).items():
            defaults.setdefault(name, {}).update(cfg)

    def _default_config(self) -> dict:
        return {
            "current_profile": next(iter(PROFILE_DEFAULTS)),
            "profiles": copy.deepcopy(PROFILE_DEFAULTS),
            "shared": {},
        }

    def save(self) -> None:
        """写回磁盘：按 workspace 分文件存覆盖值，core 存 current_profile。"""
        by_ws: dict = {}
        defaults = PROFILE_DEFAULTS
        for pname, cfg in self._data.get("profiles", {}).items():
            default = defaults.get(pname, {})
            overrides = {
                k: v for k, v in cfg.items()
                if k not in default or v != default[k]
            }
            if overrides:
                by_ws.setdefault(workspace_of(pname), {})[pname] = overrides

        for ws in WORKSPACES:
            path = self._workspace_path(ws)
            profiles = by_ws.get(ws)
            if profiles:
                self._write_json(path, {"profiles": profiles})
            elif path.exists():
                path.unlink()  # 覆盖值清空后移除文件，避免残留
        self._write_json(
            self._state_path(),
            {"current_profile": self.current_profile, "shared": self._data.get("shared", {})},
        )

    def _write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @property
    def current_profile(self) -> str:
        """获取当前激活的 Profile 名称。"""
        return self._data["current_profile"]

    @current_profile.setter
    def current_profile(self, value: str) -> None:
        """切换当前 Profile。

        Args:
            value: Profile 名称
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
        profiles.setdefault(profile, {})[key] = value
        self.save()

    def get_shared(self, ws: str, key: str, default=None):
        """获取 workspace 级共享配置项。"""
        return self._data.get("shared", {}).get(ws, {}).get(key, default)

    def set_shared(self, ws: str, key: str, value) -> None:
        """写 workspace 级共享配置项（立即落盘）。"""
        self._data.setdefault("shared", {}).setdefault(ws, {})[key] = value
        self.save()

    def list_profiles(self) -> list[str]:
        """列出所有可用 Profile 名称。"""
        return list(self._data.get("profiles", {}).keys())

    def get_profile_root(self, profile: Optional[str] = None) -> str:
        """快捷获取 Profile 的 root 路径。"""
        cfg = self.get_profile_config(profile)
        return cfg.get("root", "")

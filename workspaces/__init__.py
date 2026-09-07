"""
Workspaces — 专用选项后端。

三个业务域（对应首页 radio）：
    screen — 影视（movie + tv）
    doc    — 纪实（realshot）
    lab    — 练习（homework）

每个 workspace 定义默认 profile、可切换 profiles、以及专用菜单项。
"""

WORKSPACES = {
    "screen": {
        "label": "影视",
        "profiles": ["movie", "tv"],
        "default_profile": "movie",
        "menu": ["config", "sync"],
    },
    "doc": {
        "label": "纪实",
        "profiles": ["realshot"],
        "default_profile": "realshot",
        "menu": [],
    },
    "lab": {
        "label": "练习",
        "profiles": ["homework"],
        "default_profile": "homework",
        "menu": ["config"],
    },
}

_PROFILE_TO_WORKSPACE = {
    p: key for key, ws in WORKSPACES.items() for p in ws["profiles"]
}


def workspace_of(profile: str) -> str:
    """返回 profile 所属 workspace key。"""
    return _PROFILE_TO_WORKSPACE.get(profile, "screen")


def workspace_label(key: str) -> str:
    return WORKSPACES[key]["label"]


def workspace_menu(key: str) -> list[str]:
    return WORKSPACES[key]["menu"]


def workspace_default_profile(key: str) -> str:
    return WORKSPACES[key]["default_profile"]

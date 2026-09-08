"""首页/概览仪表盘后端 — 聚合统计数据的纯函数，不依赖 UI。"""

from workspaces import WORKSPACES, workspace_of

# 项目更新日志（首页展示，与具体工作区无关；最新在前）
CHANGELOG = [
    "按业务域拆分 core/workspaces/ui 三层架构",
    "优化同步日志与截图采集，新增停止按钮",
    "新增环境配置脚本",
]


def get_workspace_overview(config_mgr, db) -> dict:
    """聚合当前工作区概览所需的统计数据。"""
    profile = config_mgr.current_profile
    cfg = config_mgr.get_profile_config()
    row = db.fetchone(
        "SELECT timestamp FROM rename_history WHERE profile=? "
        "ORDER BY timestamp DESC LIMIT 1",
        (profile,),
    )
    # 仅列出当前工作区内的 profiles，而非全部
    ws_profiles = WORKSPACES[workspace_of(profile)]["profiles"]
    profiles = [
        {
            "key": pname,
            "name": config_mgr.get_profile_config(pname).get("name", ""),
            "count": db.get_media_count(pname),
        }
        for pname in ws_profiles
    ]
    return {
        "profile": profile,
        "display_name": cfg.get("name", ""),
        "file_count": db.get_media_count(profile),
        "total_records": sum(p["count"] for p in profiles),
        "last_sync": row["timestamp"] if row else None,
        "profiles": profiles,
        "rename_count": db.get_rename_count_by_profile(profile),
    }


def get_changelog() -> list[str]:
    """返回项目更新日志（最新在前）。"""
    return CHANGELOG

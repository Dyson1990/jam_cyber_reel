"""首页仪表盘后端 — 聚合统计数据的纯函数，不依赖 UI。"""


def get_dashboard_data(config_mgr, db) -> dict:
    """聚合首页所需的统计数据。"""
    profile = config_mgr.current_profile
    cfg = config_mgr.get_profile_config()
    row = db.fetchone(
        "SELECT timestamp FROM rename_history WHERE profile=? "
        "ORDER BY timestamp DESC LIMIT 1",
        (profile,),
    )
    profiles = [
        {
            "key": pname,
            "name": config_mgr.get_profile_config(pname).get("name", ""),
            "count": db.get_media_count(pname),
        }
        for pname in config_mgr.list_profiles()
    ]
    return {
        "profile": profile,
        "display_name": cfg.get("name", ""),
        "file_count": db.get_media_count(profile),
        "total_records": db.get_total_media_count(),
        "last_sync": row["timestamp"] if row else None,
        "profiles": profiles,
        "rename_count": db.get_rename_count_by_profile(profile),
    }

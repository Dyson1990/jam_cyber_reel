"""
独立测试脚本 — 复制代码块到 main() 下运行。

=== 纯帧提取（无需DB，直接测） ===
    from core.screenshots import resolve_time_points, extract_frame, extract_frames
    points, dur = resolve_time_points("D:/video.mp4", count=3)
    print(f"时长={dur}s 时间点={points}")
    img = extract_frame("D:/video.mp4", 60.0)
    print(f"单帧: {len(img)} bytes" if img else "提取失败")
    frames = extract_frames("D:/video.mp4", [30.0, 60.0, 120.0])
    for tp, data in frames:
        print(f"  {tp}s → {len(data)} bytes")

=== DB状态 ===
    db = Database(ROOT / "data.db")
    cfg = ConfigManager(ROOT / "profiles_config.json")
    for p in cfg.list_profiles():
        cnt = db.get_media_count(p)
        sc = db.fetchone("SELECT COUNT(*) as c FROM screenshots WHERE profile=?", (p,))
        print(f"  {p}: media={cnt}  shots={sc['c'] if sc else 0}")
    print(f"  total: {db.get_total_media_count()}")
    db.close()

=== 单文件截图 ===
    db = Database(ROOT / "data.db")
    cfg = ConfigManager(ROOT / "profiles_config.json")
    r = capture_one_video(db, "D:/path/to/video.mp4", cfg.current_profile, count=3)
    print(r)
    db.close()

=== 指定时间点截图 ===
    db = Database(ROOT / "data.db")
    cfg = ConfigManager(ROOT / "profiles_config.json")
    r = capture_one_video(db, "D:/path/to/video.mp4", cfg.current_profile, count=3, moments=[60, 120, 300])
    print(r)
    db.close()

=== 扫描目录 ===
    from core.files import scan_videos
    files = scan_videos(Path("D:/Media"), exclude_dirs=["new"])
    for f in files:
        print(f.name)

=== DB同步对比 ===
    db = Database(ROOT / "data.db")
    cfg = ConfigManager(ROOT / "profiles_config.json")
    from core.sync import diff_db
    d = diff_db(cfg.get_profile_config().get("root", ""), db, cfg.current_profile)
    print(f"added={len(d['added'])} removed={len(d['removed'])} existing={d['existing']}")
    db.close()
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from core.db import Database
from config_manager import ConfigManager
from core.screenshots import extract_frame

db = Database(ROOT / "data.db")
cfg = ConfigManager(ROOT / "profiles_config.json")

if __name__ == "__main__":
    path = r"\\TRUENAS\rust_bytes：电影\黑客帝国.The_Matrix.1999.1080p.[CHS-ENG].mp4"
    print(f"提取帧: {path}")
    r = extract_frame(path, 60)
    print(f"结果: {len(r)} bytes" if r else "结果: None（帧提取失败或文件不存在）")

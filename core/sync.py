"""
数据库同步 — 磁盘文件与 media 表对比、写入。

函数:
    diff_db(root, db, profile_name, exclude_dirs) -> dict
    sync_db(root, db, profile_name, exclude_dirs) -> int
    build_db(root, db, profile_name) -> int
"""

import os
from pathlib import Path

from core.files import scan_videos, VIDEO_EXTENSIONS


def diff_db(
    root: str, db, profile_name: str, exclude_dirs: list[str] | None = None,
) -> dict:
    """扫描 root 与 media 表对比，返回 {added, removed, existing}."""
    if not root:
        return {"added": [], "removed": [], "existing": 0}

    disk_files = scan_videos(Path(root), exclude_dirs=exclude_dirs)
    disk_set: set[str] = {os.path.normpath(str(f)) for f in disk_files}

    db_records = db.get_media_by_profile(profile_name)
    db_set: set[str] = {r["mv_path"] for r in db_records}

    added = [Path(p) for p in disk_set - db_set]
    return {
        "added": sorted(added, key=lambda p: p.name),
        "removed": sorted(db_set - disk_set),
        "existing": len(disk_set & db_set),
    }


def sync_db(
    root: str, db, profile_name: str, exclude_dirs: list[str] | None = None,
) -> int:
    """将 root 中新增文件写入 media 表，返回新增数."""
    d = diff_db(root, db, profile_name, exclude_dirs=exclude_dirs)
    count = 0
    for f in d["added"]:
        if f.exists():
            db.upsert_media(
                profile=profile_name, title=f.stem,
                mv_path=str(f), file_size=f.stat().st_size,
            )
            count += 1
    return count


def build_db(root: str, db, profile_name: str) -> int:
    """扫描 root 顶层视频文件写入 media 表，返回写入数."""
    if not root:
        return 0
    p = Path(root)
    if not p.exists():
        return 0
    count = 0
    for f in p.iterdir():
        if not f.is_file() or f.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        db.upsert_media(
            profile=profile_name, title=f.stem,
            mv_path=str(f), file_size=f.stat().st_size,
        )
        count += 1
    return count

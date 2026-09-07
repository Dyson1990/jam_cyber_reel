"""
数据库同步 — 磁盘文件与 media 表对比、写入。

函数:
    diff_db(root, db, profile_name, exclude_dirs) -> dict
    sync_db(root, db, profile_name, exclude_dirs, crid_pattern, added) -> int
    build_db(root, db, profile_name) -> int
"""

import os
import re
from pathlib import Path

from core.files import scan_videos, VIDEO_EXTENSIONS


def diff_db(
    root: str, db, profile_name: str, exclude_dirs: list[str] | None = None,
) -> dict:
    """扫描 root 与 media 表对比，返回 {added, removed, existing}。

    两侧均按 normpath + lower 比较，避免 Windows 上大小写差异导致误判
    （同一文件同时出现在 added 与 removed）。
    """
    if not root:
        return {"added": [], "removed": [], "existing": 0}

    disk_files = scan_videos(Path(root), exclude_dirs=exclude_dirs)
    disk_map = {os.path.normpath(str(f)).lower(): f for f in disk_files}
    db_map = {
        os.path.normpath(r["mv_path"]).lower(): r["mv_path"]
        for r in db.get_media_by_profile(profile_name)
    }
    added = [disk_map[k] for k in disk_map if k not in db_map]
    removed = [db_map[k] for k in db_map if k not in disk_map]
    return {
        "added": sorted(added, key=lambda p: p.name),
        "removed": sorted(removed),
        "existing": len(set(disk_map) & set(db_map)),
    }


def sync_db(
    root: str, db, profile_name: str, exclude_dirs: list[str] | None = None,
    crid_pattern: str = "", added: list | None = None,
) -> int:
    """将 root 中新增文件写入 media 表，返回新增数。

    若 crid_pattern 非空，从文件名匹配正则提取 crid：
    - 有捕获组时取 group(1)，否则取 group(0)

    added 可传入 diff_db 的结果，避免对 root 重复扫描。
    """
    if added is None:
        added = diff_db(root, db, profile_name, exclude_dirs=exclude_dirs)["added"]
    count = 0
    for f in added:
        if f.exists():
            crid = _extract_crid(f.stem, crid_pattern)
            db.upsert_media(
                profile=profile_name, title=f.stem,
                mv_path=str(f), file_size=f.stat().st_size,
                crid=crid,
            )
            count += 1
    return count


def _extract_crid(stem: str, pattern: str) -> str:
    """从文件名 stem 用正则提取 crid，pattern 为空或匹配失败返回 ''。"""
    if not pattern:
        return ""
    try:
        m = re.search(pattern, stem)
        if m:
            return m.group(1) if m.lastindex else m.group(0)
    except re.error:
        pass
    return ""


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

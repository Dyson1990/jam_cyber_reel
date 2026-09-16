"""扫描（screen）— 数据库同步。

扫 from/to/root 三目录的顶层影视文件与压缩包（不递归子目录），与 media 表对比；
写入时记录每条文件的来源（from/to/root），供标准化/知识库按来源读取。

约定（见 guide.md）：from=网上下载未经修改；to=已标准化；root=人工检查过。
"""

import os
from pathlib import Path

from core.files import VIDEO_EXTENSIONS
from core.logging_config import get_logger

logger = get_logger(__name__)

ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z"}
_MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | ARCHIVE_EXTENSIONS

# 遍历顺序：from 优先，其次 to，最后 root；跨目录同名文件先到先得。
_SOURCE_ORDER = ("from", "to", "root")


def _scan_top(path: str) -> list[Path]:
    """扫单目录顶层（不递归）影视+压缩文件，按名排序。"""
    if not path:
        return []
    p = Path(path)
    if not p.is_dir():
        return []
    return sorted(
        f for f in p.iterdir()
        if f.is_file() and f.suffix.lower() in _MEDIA_EXTENSIONS
    )


def scan_sources(cfg: dict) -> list[tuple[Path, str]]:
    """按 from/to/root 顺序收集顶层文件，返回 [(path, source)]，跨目录去重。"""
    seen: set[str] = set()
    out: list[tuple[Path, str]] = []
    for key in _SOURCE_ORDER:
        for f in _scan_top(cfg.get(key, "")):
            norm = os.path.normpath(str(f)).lower()
            if norm in seen:
                continue
            seen.add(norm)
            out.append((f, key))
    return out


def diff_db(cfg: dict, db, profile: str) -> dict:
    """对比 from/to/root 顶层文件与 media 表，返回 {added, removed, existing}。

    added 为 [(Path, source)]；两侧按 normpath+lower 比较，避免 Windows 大小写误判。
    """
    disk_map = {
        os.path.normpath(str(f)).lower(): (f, src) for f, src in scan_sources(cfg)
    }
    db_map = {
        os.path.normpath(r["mv_path"]).lower(): r["mv_path"]
        for r in db.get_media_by_profile(profile)
    }
    added = [disk_map[k] for k in disk_map if k not in db_map]
    removed = [db_map[k] for k in db_map if k not in disk_map]
    logger.info(
        "diff_db profile=%s 新增=%d 移除=%d", profile, len(added), len(removed),
    )
    return {
        "added": added,
        "removed": removed,
        "existing": len(set(disk_map) & set(db_map)),
    }


def sync_db(cfg: dict, db, profile: str, added: list | None = None) -> int:
    """将新增文件写入 media 表（记录 source），返回写入数。"""
    if added is None:
        added = diff_db(cfg, db, profile)["added"]
    count = 0
    for f, source in added:
        if not f.exists():
            continue
        db.upsert_media(
            profile=profile, title=f.stem, mv_path=str(f),
            file_size=f.stat().st_size, source=source,
        )
        count += 1
    logger.info("sync_db profile=%s 写入 %d 条", profile, count)
    return count


def media_files(db, profile: str, source: str | None = None) -> list[Path]:
    """从 media 表取文件路径；source 指定时只取该来源（from/to/root）。"""
    rows = db.get_media_by_profile(profile)
    return [
        Path(r["mv_path"]) for r in rows
        if source is None or r["source"] == source
    ]

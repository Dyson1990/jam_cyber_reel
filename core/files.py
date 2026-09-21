"""
本地文件操作 — 扫描、重命名、回滚。
"""

import os
import uuid
from pathlib import Path

from core.logging_config import get_logger

logger = get_logger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".ts"}


def is_subpath(path: str, parent: str) -> bool:
    """判断 path 是否等于 parent 或位于 parent 之下。

    大小写不敏感，且按路径边界比较——避免 "new" 误匹配 "new2"。
    """
    p = os.path.normpath(path).lower()
    par = os.path.normpath(parent).lower().rstrip(os.sep)
    if not par:
        return False
    return p == par or p.startswith(par + os.sep)


# ==================== 扫描 ====================

def scan_videos(root: Path, exclude_dirs: list[str] | None = None) -> list[Path]:
    """递归扫描目录下所有视频文件，去重，可选排除子目录。"""
    if not root or str(root) == ".":
        return []
    root_path = Path(root)
    if not root_path.exists():
        return []

    exclude_prefixes: list[str] = []
    if exclude_dirs:
        for d in exclude_dirs:
            exclude_prefixes.append(os.path.normpath(str(root_path / d)))

    seen: set[str] = set()
    files: list[Path] = []
    for f in root_path.rglob("*"):
        if f.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if f.is_dir():
            continue
        if exclude_prefixes and any(is_subpath(str(f), ep) for ep in exclude_prefixes):
            continue
        f_norm = os.path.normpath(str(f)).lower()
        if f_norm not in seen:
            seen.add(f_norm)
            files.append(f)
    return files


# ==================== 重命名 ====================

def rename_files(
    mapping: dict[Path, str],
    target_dir: Path | None,
    db,
    profile_name: str,
) -> list[dict]:
    """两阶段重命名（UUID 中转防冲突），记录到 rename_history。

    阶段2 失败时把文件从 UUID 名恢复原名，避免遗留不可识别的随机名。
    """
    records: list[dict] = []
    if target_dir is not None:
        target_dir.mkdir(parents=True, exist_ok=True)
    batch_id = uuid.uuid4().hex

    # 阶段1: → UUID
    temp: dict[Path, Path] = {}
    for old_path, new_name in mapping.items():
        parent = old_path.parent
        tmp_dest = parent / f"{uuid.uuid4().hex}{old_path.suffix}"
        try:
            old_path.rename(tmp_dest)
            temp[old_path] = tmp_dest
        except OSError as e:
            records.append({
                "old_name": old_path.name, "new_name": new_name,
                "path": str(parent), "status": f"阶段1失败: {e}",
            })

    # 阶段2: UUID → 规范名
    for old_path, new_name in mapping.items():
        tmp_dest = temp.get(old_path)
        if tmp_dest is None:
            continue
        dest_dir = target_dir or tmp_dest.parent
        final_dest = dest_dir / new_name
        if final_dest.exists() and final_dest != tmp_dest:
            stem, c = final_dest.stem, 1
            while final_dest.exists():
                final_dest = dest_dir / f"{stem}_{c}{final_dest.suffix}"
                c += 1
        try:
            tmp_dest.rename(final_dest)
        except OSError as e:
            _restore(tmp_dest, old_path)
            records.append({
                "old_name": old_path.name, "new_name": new_name,
                "path": str(dest_dir), "status": f"阶段2失败: {e}（已恢复原名）",
            })
            continue
        actual_name = final_dest.name
        db.add_rename_history(
            old_name=old_path.name, new_name=actual_name,
            path=str(dest_dir), profile=profile_name, batch_id=batch_id,
        )
        records.append({
            "old_name": old_path.name, "new_name": actual_name,
            "path": str(dest_dir), "status": "成功",
        })
    ok = sum(1 for r in records if r["status"] == "成功")
    fail = len(records) - ok
    logger.info("rename_files batch=%s 成功=%d 失败=%d", batch_id, ok, fail)
    if fail:
        logger.warning("rename_files batch=%s 有 %d 条失败", batch_id, fail)
    return records


def _restore(tmp_dest: Path, original: Path) -> None:
    """阶段2失败时，把 UUID 中转文件恢复为原名。"""
    try:
        if tmp_dest.exists():
            tmp_dest.rename(original)
    except OSError:
        pass


# ==================== 回滚 ====================

def rollback_records(records: list, db, source_dir: Path | None = None) -> list[dict]:
    """回滚一批重命名记录：从 path/new_name 移回 source_dir/old_name。

    目标名已存在时追加序号而非覆盖，避免破坏已有文件。
    """
    results: list[dict] = []
    for rec in records:
        cur = Path(rec["path"]) / rec["new_name"]
        orig_dir = source_dir or Path(rec["path"])
        orig = orig_dir / rec["old_name"]
        if cur.exists():
            try:
                orig_dir.mkdir(parents=True, exist_ok=True)
                if orig.exists():
                    stem, c = orig.stem, 1
                    while orig.exists():
                        orig = orig_dir / f"{stem}_{c}{orig.suffix}"
                        c += 1
                cur.rename(orig)
                db.delete_rename_history(rec["id"])
                results.append({
                    "old_name": rec["new_name"], "new_name": orig.name,
                    "path": str(orig_dir), "status": "已回滚",
                })
            except OSError as e:
                results.append({
                    "old_name": rec["new_name"], "new_name": rec["old_name"],
                    "path": str(orig_dir), "status": f"回滚失败: {e}",
                })
        else:
            db.delete_rename_history(rec["id"])
            results.append({
                "old_name": rec["new_name"], "new_name": rec["old_name"],
                "path": str(orig_dir), "status": "文件已不存在，记录已清除",
            })
    rolled = sum(1 for r in results if "已回滚" in r.get("status", ""))
    failed = sum(1 for r in results if "失败" in r.get("status", ""))
    logger.info("rollback_records 已回滚=%d 失败=%d", rolled, failed)
    return results


# ==================== TV 三级结构搬移 ====================

def _rel_to(p: Path, base: Path) -> str:
    """p 相对 base 的 POSIX 路径；不在 base 下时退回绝对路径。"""
    try:
        return p.relative_to(base).as_posix()
    except ValueError:
        return p.as_posix()


def _rm_empty_up(base: Path, dirs: set[Path]) -> None:
    """自底向上删除 base 下的空目录（不含 base 本身）。"""
    for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        cur = d
        while cur != base and cur.exists() and cur.is_dir() and not any(cur.iterdir()):
            cur.rmdir()
            cur = cur.parent


def move_to_structure(
    mapping: dict[Path, str], target_dir: Path, source_dir: Path, db, profile_name: str,
) -> list[dict]:
    """TV 三级结构搬移：{原文件绝对路径: 新相对路径} → 移到 target_dir/新相对路径（逐级建目录）。

    与原 rename_files 不同：新路径带子目录（系列/季），需逐级 mkdir；搬空后删除 source_dir 下空目录。
    历史记录 old_name/new_name 均存相对路径（source_dir/target_dir 为基），供结构回滚重建目录。
    """
    records: list[dict] = []
    target_dir.mkdir(parents=True, exist_ok=True)
    batch_id = uuid.uuid4().hex
    for old_path, new_rel in mapping.items():
        new_abs = target_dir / new_rel
        new_abs.parent.mkdir(parents=True, exist_ok=True)
        if new_abs.exists():
            stem, c = new_abs.stem, 1
            while new_abs.exists():
                new_abs = new_abs.parent / f"{stem}_{c}{new_abs.suffix}"
                c += 1
        try:
            old_path.rename(new_abs)
        except OSError as e:
            records.append({
                "old_name": _rel_to(old_path, source_dir), "new_name": new_rel,
                "path": str(new_abs.parent), "status": f"失败: {e}",
            })
            continue
        rel_old = _rel_to(old_path, source_dir)
        db.add_rename_history(rel_old, new_rel, str(target_dir), profile_name, batch_id)
        records.append({
            "old_name": rel_old, "new_name": new_rel,
            "path": str(new_abs.parent), "status": "成功",
        })
    _rm_empty_up(source_dir, {p.parent for p in mapping})
    return records


def rollback_structure(records: list, db, source_dir: Path) -> list[dict]:
    """TV 结构回滚：把新相对路径移回原相对路径（source_dir 下重建目录），并删空 target 下空目录。"""
    results: list[dict] = []
    to_root: Path | None = None
    to_dirs: set[Path] = set()
    for rec in records:
        path = rec["path"]
        new_rel = rec["new_name"]
        old_rel = rec["old_name"]
        if to_root is None:
            to_root = Path(path)
        cur = Path(path) / new_rel
        orig = source_dir / old_rel
        if cur.exists():
            try:
                orig.parent.mkdir(parents=True, exist_ok=True)
                if orig.exists():
                    stem, c = orig.stem, 1
                    while orig.exists():
                        orig = orig.parent / f"{stem}_{c}{orig.suffix}"
                        c += 1
                cur.rename(orig)
                db.delete_rename_history(rec["id"])
                to_dirs.add(cur.parent)
                results.append({
                    "old_name": new_rel, "new_name": old_rel,
                    "path": str(orig.parent), "status": "已回滚",
                })
            except OSError as e:
                results.append({
                    "old_name": new_rel, "new_name": old_rel,
                    "path": str(orig.parent), "status": f"回滚失败: {e}",
                })
        else:
            db.delete_rename_history(rec["id"])
            to_dirs.add(cur.parent)
            results.append({
                "old_name": new_rel, "new_name": old_rel,
                "path": str(orig.parent), "status": "文件已不存在，记录已清除",
            })
    if to_root is not None and to_dirs:
        _rm_empty_up(to_root, to_dirs)
    return results

"""
本地文件操作 — 扫描、重命名、回滚。
"""

import os
import uuid
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".ts"}


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
            exclude_prefixes.append(os.path.normpath(str(root_path / d)).lower())

    seen: set[str] = set()
    files: list[Path] = []
    for f in root_path.rglob("*"):
        if f.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if f.is_dir():
            continue
        f_norm = os.path.normpath(str(f)).lower()
        if exclude_prefixes and any(f_norm.startswith(ep) for ep in exclude_prefixes):
            continue
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
    """两阶段重命名（UUID 中转防冲突），记录到 rename_history。"""
    records: list[dict] = []

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
            actual_name = final_dest.name
            db.add_rename_history(
                old_name=old_path.name, new_name=actual_name,
                path=str(dest_dir), profile=profile_name,
            )
            records.append({
                "old_name": old_path.name, "new_name": actual_name,
                "path": str(dest_dir), "status": "成功",
            })
        except OSError as e:
            records.append({
                "old_name": old_path.name, "new_name": new_name,
                "path": str(dest_dir), "status": f"阶段2失败: {e}",
            })
    return records


# ==================== 回滚 ====================

def rollback_records(records: list, db, source_dir: Path | None = None) -> list[dict]:
    """回滚一批重命名记录：从 path/new_name 移回 source_dir/old_name。"""
    results: list[dict] = []
    for rec in records:
        cur = Path(rec["path"]) / rec["new_name"]
        orig_dir = source_dir or Path(rec["path"])
        orig = orig_dir / rec["old_name"]
        if cur.exists():
            try:
                if orig.exists():
                    orig.unlink()
                orig_dir.mkdir(parents=True, exist_ok=True)
                cur.rename(orig)
                db.delete_rename_history(rec["id"])
                results.append({
                    "old_name": rec["new_name"], "new_name": rec["old_name"],
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
    return results

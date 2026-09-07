"""媒体浏览器后端 — 记录过滤与格式化，不依赖 UI。"""

import os

from core.files import is_subpath


def get_exclude_dirs(root: str, *sub_paths: str) -> list[str]:
    """返回 root 下需排除的子目录（sub_path 严格位于 root 下时返回其路径）。"""
    if not root:
        return []
    result: list[str] = []
    for sp in sub_paths:
        if not sp:
            continue
        if is_subpath(sp, root) and not is_subpath(root, sp):
            result.append(os.path.normpath(sp).lower())
    return result


def get_relative_exclude_dirs(root: str, *sub_paths: str) -> list[str]:
    """返回 sub_path 相对 root 的首段相对目录名（供 scan_videos 使用）。"""
    if not root:
        return []
    root_norm = os.path.normpath(root)
    result: list[str] = []
    for sp in sub_paths:
        if not sp:
            continue
        if is_subpath(sp, root) and not is_subpath(root, sp):
            rel = os.path.normpath(sp)[len(root_norm):].lstrip(os.sep)
            if rel:
                result.append(rel.split(os.sep)[0])
    return result


def filter_records(records: list, cfg: dict) -> tuple[list, bool]:
    """过滤仅 root 路径下、且不在 from/to 下的记录。

    Returns:
        (过滤后的记录, root_mismatch)  — root 不匹配任何记录时为 True
    """
    root = cfg.get("root", "")
    if not root or not records:
        return list(records), False
    exclude_prefixes = get_exclude_dirs(root, cfg.get("from", ""), cfg.get("to", ""))
    filtered = [
        r for r in records
        if is_subpath(r["mv_path"], root)
        and not any(is_subpath(r["mv_path"], ep) for ep in exclude_prefixes)
    ]
    if filtered:
        return filtered, False
    return list(records), True


def format_cell(value, col: dict) -> str:
    """根据列类型格式化单元格显示值。"""
    if value is None:
        return "—"
    col_type = col.get("type", "TEXT")
    if col_type == "INTEGER" and col["name"] == "file_size":
        return format_size(int(value))
    if col_type == "REAL" and isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def format_size(size_bytes: int) -> str:
    """字节数 → 人类可读大小。"""
    if size_bytes <= 0:
        return "—"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} B"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"

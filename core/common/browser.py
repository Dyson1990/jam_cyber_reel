"""媒体浏览器后端 — 记录过滤与格式化，不依赖 UI。"""

import os


def get_exclude_dirs(root: str, *sub_paths: str) -> list[str]:
    """返回 root 下需排除的子目录（sub_path 在 root 下时返回其完整路径）。"""
    if not root:
        return []
    root_norm = os.path.normpath(root).lower()
    result: list[str] = []
    for sp in sub_paths:
        if not sp:
            continue
        sp_norm = os.path.normpath(sp).lower()
        if sp_norm.startswith(root_norm) and sp_norm != root_norm:
            result.append(sp_norm)
    return result


def filter_records(records: list, cfg: dict) -> tuple[list, bool]:
    """过滤仅 root 路径下、且不在 from/to 下的记录。

    Returns:
        (过滤后的记录, root_mismatch)  — root 不匹配任何记录时为 True
    """
    root = cfg.get("root", "")
    if not root or not records:
        return list(records), False
    root_norm = os.path.normpath(root).lower()
    exclude_prefixes = get_exclude_dirs(root, cfg.get("from", ""), cfg.get("to", ""))
    filtered = []
    for r in records:
        rp = os.path.normpath(r["mv_path"]).lower()
        if not rp.startswith(root_norm):
            continue
        if any(rp.startswith(ep) for ep in exclude_prefixes):
            continue
        filtered.append(r)
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

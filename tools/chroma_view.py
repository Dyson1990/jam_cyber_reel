"""查看 chromadb 存储目录（chroma.sqlite3 + HNSW 段）内的集合数据。

用法: python tools/chroma_view.py [相对路径] [--json]

相对路径相对项目根，缺省为 workspaces/screen/knowledge_base/storage；默认按集合
以二维表打印元数据，加 --json 则输出完整 JSON（含 raw 全量）。仅读不写。
"""
import json
import sys
from pathlib import Path

import chromadb

ROOT = Path(__file__).resolve().parent.parent

# 表头 → metadata 键；raw 为各源一手全量数据，正文太长，仅在 --json 模式输出
_COLS = (("zh", "中文名"), ("en", "英文名"), ("year", "年份"), ("score", "评分"), ("title", "title"))


def _w(s: str) -> int:
    """终端显示宽度：CJK 全角按 2 列计，用于对齐。"""
    return sum(2 if ord(c) > 0x2E80 else 1 for c in str(s))


def _pad(s: str, width: int) -> str:
    return str(s) + " " * max(0, width - _w(s))


def _human(col) -> None:
    res = col.get()
    ids = res.get("ids", [])
    metas = res.get("metadatas", []) or [{}] * len(ids)
    rows = [[m.get(k, "") for k, _ in _COLS] for m in metas]
    heads = [h for _, h in _COLS]
    widths = [max(_w(h), *( _w(r[i]) for r in rows)) for i, h in enumerate(heads)]

    print(f"== collection: {col.name} (共 {len(ids)} 条) ==")
    print("  " + " | ".join(_pad(h, widths[i]) for i, h in enumerate(heads)))
    print("  " + "-+-".join("-" * w for w in widths))
    for r in rows:
        print("  " + " | ".join(_pad(c, widths[i]) for i, c in enumerate(r)))


def _json(col) -> None:
    print(json.dumps(col.get(), ensure_ascii=False, indent=2))


def main():
    # Windows 终端默认 GBK，强制 UTF-8 避免中文/韩文打印报错或乱码
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    # 首个非 -- 开头参数为相对路径，缺省默认看 screen 知识库
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = ROOT / (args[0] if args else "workspaces/screen/knowledge_base/storage")
    if not (path / "chroma.sqlite3").exists():
        print(f"未找到 chroma.sqlite3: {path}")
        return
    as_json = "--json" in sys.argv
    client = chromadb.PersistentClient(path=str(path.resolve()))
    for col in client.list_collections():
        _json(col) if as_json else _human(col)


if __name__ == "__main__":
    main()

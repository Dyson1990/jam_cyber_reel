"""ATTACH 两个 SQLite 库，对指定表的指定字段求差集。"""
import sys
import sqlite3
from pathlib import Path

THIS_DB = Path(__file__).resolve().parent.parent / "data.db"


def _q(ident: str) -> str:
    """SQL 标识符安全引用（双引号包裹并转义内部引号）。"""
    return '"' + ident.replace('"', '""') + '"'


def diff(external_db: str, table: str, field: str, swap: bool = False):
    if not Path(external_db).exists():
        print(f"外部库不存在: {external_db}")
        return
    if not THIS_DB.exists():
        print(f"data.db 不存在: {THIS_DB}")
        return

    conn = sqlite3.connect(f"file:{THIS_DB}?mode=ro", uri=True)
    conn.execute(f"ATTACH DATABASE ? AS ext", (str(Path(external_db).resolve()),))

    a, b = ("ext", "main") if swap else ("main", "ext")
    qf, qt = _q(field), _q(table)
    rows = conn.execute(
        f'SELECT DISTINCT {qf} FROM {a}.{qt} WHERE {qf} IS NOT NULL '
        f'AND {qf} NOT IN (SELECT {qf} FROM {b}.{qt} WHERE {qf} IS NOT NULL)'
    ).fetchall()

    if not rows:
        print("(无差异)")
        return

    for r in rows:
        print(r[0])
    print(f"\n共 {len(rows)} 条 → [{a}] 有 [{b}] 无")


def main():
    if len(sys.argv) < 4:
        print("用法: python tools/db_diff.py <外部db路径> <表名> <字段名> [--swap]")
        print("默认: data.db 有而外部库无。加 --swap 则反向。")
        return
    external_db = sys.argv[1]
    table = sys.argv[2]
    field = sys.argv[3]
    swap = "--swap" in sys.argv
    diff(external_db, table, field, swap)


if __name__ == "__main__":
    main()

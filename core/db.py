"""
数据库模块 - 统一封装所有 SQLite 操作。
与 UI 完全分离，UI 层禁止直接操作 SQLite。

主要类：
    Database: 数据库连接与操作封装

数据表：
    rename_history - 文件重命名历史（支持 rollback），所有 Profile 共享
    media_{profile} - 每种 Profile 独立的媒体表（movie/tv/realshot/homework）

设计理由：
    每种 Profile 使用独立表，表结构可在配置页调整。
    基础列（id/title/mv_path/cover/added_time）始终存在，
    扩展列由各 Profile 的 table_schema 配置定义。

调用流程：
    main.py → Database 实例 → 各 Profile handler / UI 页面通过该实例读写
"""

import sqlite3
import threading
from pathlib import Path
from typing import Optional, Any


class Database:
    """SQLite 数据库统一封装，线程安全。

    设计理由：
        - 所有 SQL 操作集中于此，避免散落各处导致维护困难
        - 使用 thread-local 连接，支持 NiceGUI 的多线程异步模型
        - check_same_thread=False 配合 threading.local 实现轻量线程安全
    """

    def __init__(self, db_path: Path):
        """初始化数据库连接。

        Args:
            db_path: SQLite 数据库文件路径（Path 对象）
        """
        self.db_path = db_path
        self._local = threading.local()

    def _get_conn(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接，自动创建。

        Returns:
            当前线程的 sqlite3.Connection
        """
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path), check_same_thread=False
            )
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """执行写操作（INSERT/UPDATE/DELETE），自动提交。

        Args:
            sql: SQL 语句
            params: 参数元组

        Returns:
            sqlite3.Cursor
        """
        conn = self._get_conn()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """执行查询，返回全部结果。

        Args:
            sql: SQL 语句
            params: 参数元组

        Returns:
            sqlite3.Row 列表
        """
        conn = self._get_conn()
        return conn.execute(sql, params).fetchall()

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        """执行查询，返回单条结果。

        Args:
            sql: SQL 语句
            params: 参数元组

        Returns:
            单条 sqlite3.Row 或 None
        """
        conn = self._get_conn()
        return conn.execute(sql, params).fetchone()

    # ==================== 表创建 ====================

    def create_tables(self) -> None:
        """创建共享表。

        设计理由：
            使用 IF NOT EXISTS，支持重复调用而不会出错，
            便于 create_test_db.py 和 main.py 均可安全调用。

        media_{profile} 表由 create_media_table() 按需创建。
        """
        self.execute("""
            CREATE TABLE IF NOT EXISTS rename_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                old_name TEXT NOT NULL,
                new_name TEXT NOT NULL,
                path TEXT NOT NULL,
                profile TEXT NOT NULL,
                timestamp TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )
        """)
        self.execute("""
            CREATE TABLE IF NOT EXISTS screenshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mv_path TEXT NOT NULL,
                profile TEXT NOT NULL,
                image BLOB NOT NULL,
                time_point REAL DEFAULT 0.0,
                time_label TEXT DEFAULT '',
                is_cover INTEGER DEFAULT 0,
                added_time TEXT DEFAULT (datetime('now','localtime'))
            )
        """)

    def create_media_table(self, profile: str, columns: list[dict]) -> None:
        """为指定 Profile 创建独立的媒体表。

        基础列（始终存在，无需在 schema 中定义）：
            id, title, mv_path, cover, added_time

        Args:
            profile: Profile 名称（如 movie/tv/realshot/homework）
            columns: 扩展列定义列表，每项 {"name": str, "type": str}
        """
        table = f"media_{profile}"
        col_defs = [
            "id INTEGER PRIMARY KEY AUTOINCREMENT",
            "title TEXT NOT NULL",
            "mv_path TEXT NOT NULL UNIQUE",
            "cover BLOB",
            "crid TEXT DEFAULT ''",
            "added_time TEXT DEFAULT (datetime('now','localtime'))",
        ]
        for col in columns:
            name = col["name"]
            col_type = col.get("type", "TEXT")
            col_defs.append(f"{name} {col_type}")

        sql = f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(col_defs)})"
        self.execute(sql)
        # 迁移：v1 表缺少 crid 列
        try:
            self.execute(f"ALTER TABLE {table} ADD COLUMN crid TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass

    def ensure_all_media_tables(self, config_mgr) -> None:
        """根据配置为所有 Profile 创建媒体表。

        Args:
            config_mgr: ConfigManager 实例
        """
        for pname in config_mgr.list_profiles():
            cfg = config_mgr.get_profile_config(pname)
            schema = cfg.get("table_schema", [])
            self.create_media_table(pname, schema)

    def get_media_columns(self, profile: str) -> list[str]:
        """获取指定 Profile 媒体表的所有列名（用于动态渲染）。

        Args:
            profile: Profile 名称

        Returns:
            列名列表
        """
        table = f"media_{profile}"
        rows = self.fetchall(f"PRAGMA table_info({table})")
        return [r["name"] for r in rows] if rows else []

    # ==================== rename_history 操作 ====================

    def add_rename_history(
        self, old_name: str, new_name: str, path: str, profile: str
    ) -> None:
        """记录一次重命名操作，用于后续 rollback。

        Args:
            old_name: 原文件名
            new_name: 新文件名
            path: 文件所在目录
            profile: 所属 Profile 名称
        """
        self.execute(
            "INSERT INTO rename_history (old_name, new_name, path, profile) "
            "VALUES (?, ?, ?, ?)",
            (old_name, new_name, path, profile),
        )

    def get_rename_history(
        self, profile: str, limit: int = 100
    ) -> list[sqlite3.Row]:
        """获取指定 Profile 的重命名历史，按时间倒序。

        Args:
            profile: Profile 名称
            limit: 最大返回条数

        Returns:
            sqlite3.Row 列表
        """
        return self.fetchall(
            "SELECT * FROM rename_history WHERE profile=? "
            "ORDER BY timestamp DESC LIMIT ?",
            (profile, limit),
        )

    def get_last_rename(self, profile: str) -> Optional[sqlite3.Row]:
        """获取最近一次重命名记录。

        Args:
            profile: Profile 名称

        Returns:
            最近一条记录或 None
        """
        return self.fetchone(
            "SELECT * FROM rename_history WHERE profile=? "
            "ORDER BY id DESC LIMIT 1",
            (profile,),
        )

    def get_last_batch(self, profile: str, window_sec: int = 5) -> list[sqlite3.Row]:
        """获取最近一批重命名记录（最近一条 ± window_sec 内的所有记录）。"""
        last = self.get_last_rename(profile)
        if not last:
            return []
        ts = last["timestamp"]
        return self.fetchall(
            "SELECT * FROM rename_history WHERE profile=? "
            "AND timestamp BETWEEN datetime(?, ?) AND datetime(?, ?) "
            "ORDER BY id",
            (profile, ts, f"-{window_sec} seconds", ts, f"+{window_sec} seconds"),
        )

    def get_rename_by_date_range(
        self, profile: str, start_date: str, end_date: str
    ) -> list[sqlite3.Row]:
        """获取指定日期范围内的重命名记录（日期格式: YYYY-MM-DD）。"""
        return self.fetchall(
            "SELECT * FROM rename_history WHERE profile=? "
            "AND date(timestamp) BETWEEN ? AND ? "
            "ORDER BY id",
            (profile, start_date, end_date),
        )

    def delete_rename_records(self, ids: list[int]) -> None:
        """批量删除重命名记录。"""
        if not ids:
            return
        placeholders = ", ".join("?" * len(ids))
        self.execute(
            f"DELETE FROM rename_history WHERE id IN ({placeholders})",
            tuple(ids),
        )

    def delete_rename_history(self, record_id: int) -> None:
        """删除单条重命名记录（rollback 后调用）。

        Args:
            record_id: 记录 ID
        """
        self.execute("DELETE FROM rename_history WHERE id=?", (record_id,))

    def clear_rename_history(self, profile: str) -> None:
        """清空指定 Profile 的全部重命名历史（rollback_all 后调用）。

        Args:
            profile: Profile 名称
        """
        self.execute(
            "DELETE FROM rename_history WHERE profile=?", (profile,)
        )

    def get_rename_count_by_profile(self, profile: str) -> int:
        """获取指定 Profile 的重命名操作总数。

        Args:
            profile: Profile 名称

        Returns:
            操作计数
        """
        row = self.fetchone(
            "SELECT COUNT(*) as cnt FROM rename_history WHERE profile=?",
            (profile,),
        )
        return row["cnt"] if row else 0

    # ==================== media 操作（按 Profile 分表） ====================

    def upsert_media(
        self,
        profile: str,
        title: str,
        mv_path: str,
        cover: Optional[bytes] = None,
        **extra,
    ) -> None:
        """插入或更新媒体记录到 media_{profile} 表。

        基础列 title/mv_path/cover 固定传入，
        扩展列通过 **extra 动态传入（匹配 table_schema 中的列名）。

        Args:
            profile: 所属 Profile（决定写入哪个表）
            title: 标题
            mv_path: 文件完整路径
            cover: 封面图片 BLOB
            **extra: 扩展列键值对
        """
        table = f"media_{profile}"
        columns = ["title", "mv_path", "cover"]
        values: list = [title, mv_path, cover]
        for k, v in extra.items():
            columns.append(k)
            values.append(v)

        placeholders = ", ".join(["?"] * len(columns))
        col_names = ", ".join(columns)
        sql = (
            f"INSERT OR REPLACE INTO {table} ({col_names}) "
            f"VALUES ({placeholders})"
        )
        self.execute(sql, tuple(values))

    def get_media_by_profile(self, profile: str) -> list[sqlite3.Row]:
        """获取指定 Profile 的全部媒体记录。

        Args:
            profile: Profile 名称

        Returns:
            sqlite3.Row 列表
        """
        table = f"media_{profile}"
        return self.fetchall(
            f"SELECT * FROM {table} ORDER BY mv_path, title"
        )

    def get_media_count(self, profile: str) -> int:
        """获取指定 Profile 的媒体数量。

        Args:
            profile: Profile 名称

        Returns:
            媒体计数
        """
        table = f"media_{profile}"
        row = self.fetchone(f"SELECT COUNT(*) as cnt FROM {table}")
        return row["cnt"] if row else 0

    def get_total_media_count(self) -> int:
        """获取全部 Profile 的媒体总数。

        遍历所有 media_* 表并汇总计数。
        """
        tables = self.fetchall(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name LIKE 'media_%'"
        )
        total = 0
        for t in tables:
            row = self.fetchone(
                f"SELECT COUNT(*) as cnt FROM {t['name']}"
            )
            if row:
                total += row["cnt"]
        return total

    # ==================== screenshots 操作 ====================

    def add_screenshot(
        self,
        mv_path: str,
        profile: str,
        image: bytes,
        time_point: float = 0.0,
        time_label: str = "",
    ) -> int:
        """插入一张截图。

        Args:
            mv_path: 对应的视频文件路径
            profile: 所属 Profile
            image: 截图 PNG 字节数据
            time_point: 截图时间点（秒）
            time_label: 时间点标签（如 "00:01:00"）

        Returns:
            新记录的 ID
        """
        cur = self.execute(
            "INSERT INTO screenshots (mv_path, profile, image, time_point, time_label) "
            "VALUES (?, ?, ?, ?, ?)",
            (mv_path, profile, image, time_point, time_label),
        )
        return cur.lastrowid

    def get_screenshots(self, mv_path: str) -> list[sqlite3.Row]:
        """获取指定视频的全部截图，按时间点排序。

        Args:
            mv_path: 视频文件路径

        Returns:
            sqlite3.Row 列表
        """
        return self.fetchall(
            "SELECT * FROM screenshots WHERE mv_path=? ORDER BY time_point",
            (mv_path,),
        )

    def get_cover_screenshot(self, mv_path: str) -> Optional[bytes]:
        """获取优先用作封面的截图。

        优先级：is_cover=1 > 有 time_label > 第一张。

        Args:
            mv_path: 视频文件路径

        Returns:
            截图 BLOB 或 None
        """
        # 优先取 is_cover 标记的
        row = self.fetchone(
            "SELECT image FROM screenshots WHERE mv_path=? AND is_cover=1 LIMIT 1",
            (mv_path,),
        )
        if row:
            return row["image"]
        # 其次取有 time_label 的
        row = self.fetchone(
            "SELECT image FROM screenshots WHERE mv_path=? AND time_label!='' "
            "ORDER BY time_point LIMIT 1",
            (mv_path,),
        )
        if row:
            return row["image"]
        # 最后取第一张
        row = self.fetchone(
            "SELECT image FROM screenshots WHERE mv_path=? ORDER BY time_point LIMIT 1",
            (mv_path,),
        )
        return row["image"] if row else None

    def delete_screenshots(self, mv_path: str) -> None:
        """删除指定视频的全部截图。

        Args:
            mv_path: 视频文件路径
        """
        self.execute("DELETE FROM screenshots WHERE mv_path=?", (mv_path,))

    def get_screenshot_count(self, mv_path: str) -> int:
        """获取指定视频的截图数量。"""
        row = self.fetchone(
            "SELECT COUNT(*) as cnt FROM screenshots WHERE mv_path=?",
            (mv_path,),
        )
        return row["cnt"] if row else 0

    def close(self) -> None:
        """关闭当前线程的数据库连接。"""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

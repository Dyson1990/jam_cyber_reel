"""
核心纯函数单元测试（stdlib unittest，无需 pytest / 无需真实视频）。

覆盖：
    core/common/browser.py  — get_exclude_dirs / filter_records / format_cell / format_size
    core/sync.py            — _extract_crid / diff_db / build_db
    core/files.py           — scan_videos / rename_files / rollback_records
    core/screenshots.py     — format_time_label
    profiles/__init__.py    — _apply_rules
    profiles/homework/handler.py — HomeworkHandler.normalize
    workspaces/_shared.py   — parse_naming_rules / parse_table_schema / save_config
    config_manager.py       — ConfigManager
    tools/cipher.py         — cipher
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.common.browser import get_exclude_dirs, filter_records, format_cell, format_size
from core.sync import _extract_crid, diff_db, build_db
from core.files import scan_videos, rename_files, rollback_records, is_subpath
from core.screenshots import format_time_label
from core.db import Database
from profiles import _apply_rules
from profiles.homework.handler import HomeworkHandler
from workspaces import _shared as shared
from config_manager import ConfigManager
from tools.cipher import cipher


class FakeDB:
    """最小假 DB：仅实现被测函数用到的接口。"""

    def __init__(self):
        self.history = []
        self.media = {}

    def add_rename_history(self, old_name, new_name, path, profile, batch_id=""):
        self.history.append(
            {"id": len(self.history) + 1, "old_name": old_name,
             "new_name": new_name, "path": path, "profile": profile,
             "batch_id": batch_id}
        )

    def delete_rename_history(self, record_id):
        self.history = [r for r in self.history if r["id"] != record_id]

    def get_media_by_profile(self, profile):
        return [{"mv_path": p} for p in self.media.get(profile, [])]

    def upsert_media(self, profile, title, mv_path, cover=None, **extra):
        self.media.setdefault(profile, []).append(mv_path)


class FakeConfigMgr:
    def __init__(self, cfg):
        self.cfg = cfg

    def get_profile_config(self, profile=None):
        return self.cfg


# ==================== 格式化 ====================

class TestFormatting(unittest.TestCase):
    def test_format_time_label(self):
        self.assertEqual(format_time_label(0), "00:00:00")
        self.assertEqual(format_time_label(3661.7), "01:01:01")
        self.assertEqual(format_time_label(59.99), "00:00:59")

    def test_format_size(self):
        self.assertEqual(format_size(0), "—")
        self.assertEqual(format_size(-1), "—")
        self.assertEqual(format_size(500), "500 B")
        self.assertEqual(format_size(1536), "1.5 KB")

    def test_format_cell_none_and_integer(self):
        self.assertEqual(format_cell(None, {"name": "x", "type": "TEXT"}), "—")
        self.assertEqual(
            format_cell(1536, {"name": "file_size", "type": "INTEGER"}), "1.5 KB"
        )
        self.assertEqual(format_cell(5, {"name": "year", "type": "INTEGER"}), "5")


# ==================== 浏览器过滤 ====================

class TestBrowserFilter(unittest.TestCase):
    def test_get_exclude_dirs(self):
        root = r"C:\Media"
        subs = get_exclude_dirs(root, r"C:\Media\new", r"C:\Media\standardized", "")
        self.assertEqual(
            subs, [os.path.normpath(r"C:\Media\new").lower(),
                   os.path.normpath(r"C:\Media\standardized").lower()]
        )

    def test_get_exclude_dirs_ignores_outside(self):
        self.assertEqual(get_exclude_dirs(r"C:\Media", r"D:\Other"), [])

    def test_filter_records_keeps_root_only(self):
        cfg = {"root": r"C:\Media", "from": "", "to": ""}
        records = [
            {"mv_path": r"C:\Media\a.mp4"},
            {"mv_path": r"D:\Else\b.mp4"},
        ]
        kept, mismatch = filter_records(records, cfg)
        self.assertEqual(len(kept), 1)
        self.assertFalse(mismatch)

    def test_filter_records_root_mismatch(self):
        cfg = {"root": r"C:\Media", "from": "", "to": ""}
        records = [{"mv_path": r"D:\Else\b.mp4"}]
        kept, mismatch = filter_records(records, cfg)
        self.assertEqual(len(kept), 1)
        self.assertTrue(mismatch)

    def test_is_subpath_boundary(self):
        self.assertTrue(is_subpath(r"C:\Media\new\a.mp4", r"C:\Media\new"))
        self.assertFalse(is_subpath(r"C:\Media\new2\a.mp4", r"C:\Media\new"))
        self.assertTrue(is_subpath(r"c:\media\new\a.mp4", r"C:\MEDIA\new"))  # 大小写
        self.assertTrue(is_subpath(r"C:\Media\new", r"C:\Media\new"))  # 等于自身


# ==================== sync ====================

class TestSync(unittest.TestCase):
    def test_extract_crid_group(self):
        self.assertEqual(_extract_crid("CRID-12345", r"CRID-(\d+)"), "12345")

    def test_extract_crid_no_group(self):
        self.assertEqual(_extract_crid("ABC", r"ABC"), "ABC")

    def test_extract_crid_empty_or_invalid(self):
        self.assertEqual(_extract_crid("abc", ""), "")
        self.assertEqual(_extract_crid("abc", "("), "")  # 非法正则

    def test_diff_db_added_removed(self):
        db = FakeDB()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "new.mp4").write_bytes(b"x")
            db.media["movie"] = [os.path.normpath(str(root / "gone.mp4"))]
            diff = diff_db(str(root), db, "movie")
            self.assertEqual([p.name for p in diff["added"]], ["new.mp4"])
            self.assertEqual([Path(p).name for p in diff["removed"]], ["gone.mp4"])

    def test_build_db_only_top_level(self):
        db = FakeDB()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.mp4").write_bytes(b"x")
            (root / "sub").mkdir()
            (root / "sub" / "b.mp4").write_bytes(b"x")
            (root / "note.txt").write_bytes(b"x")
            n = build_db(str(root), db, "homework")
            self.assertEqual(n, 1)  # 仅顶层视频，忽略子目录与 txt

    def test_diff_db_case_insensitive(self):
        db = FakeDB()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "Old.mp4").write_bytes(b"x")
            db.media["movie"] = [os.path.normpath(str(root / "old.mp4"))]  # 大小写不同
            diff = diff_db(str(root), db, "movie")
            self.assertEqual(diff["added"], [])
            self.assertEqual(diff["removed"], [])
            self.assertEqual(diff["existing"], 1)


# ==================== files ====================

class TestFiles(unittest.TestCase):
    def test_scan_videos_exclude_and_case(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.MP4").write_bytes(b"x")
            (root / "b.mkv").write_bytes(b"x")
            (root / "new").mkdir()
            (root / "new" / "c.mp4").write_bytes(b"x")
            (root / "note.txt").write_bytes(b"x")
            files = scan_videos(root, exclude_dirs=["new"])
            names = sorted(f.name for f in files)
            self.assertEqual(names, ["a.MP4", "b.mkv"])

    def test_rename_files_two_phase_and_history(self):
        db = FakeDB()
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "from"
            dst = Path(d) / "to"
            src.mkdir()
            dst.mkdir()
            (src / "a.mp4").write_bytes(b"x")
            records = rename_files({src / "a.mp4": "b.mp4"}, dst, db, "movie")
            self.assertFalse((src / "a.mp4").exists())
            self.assertTrue((dst / "b.mp4").exists())
            self.assertEqual(records[0]["status"], "成功")
            self.assertEqual(db.history[0]["old_name"], "a.mp4")
            self.assertEqual(db.history[0]["new_name"], "b.mp4")

    def test_rename_files_collision_appends_suffix(self):
        db = FakeDB()
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "from"
            dst = Path(d) / "to"
            src.mkdir()
            dst.mkdir()
            (src / "a1.mp4").write_bytes(b"1")
            (src / "a2.mp4").write_bytes(b"2")
            mapping = {src / "a1.mp4": "b.mp4", src / "a2.mp4": "b.mp4"}
            rename_files(mapping, dst, db, "movie")
            names = sorted(p.name for p in dst.iterdir())
            self.assertEqual(names, ["b.mp4", "b_1.mp4"])

    def test_rollback_records_restores(self):
        db = FakeDB()
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "from"
            dst = Path(d) / "to"
            src.mkdir()
            dst.mkdir()
            (src / "a.mp4").write_bytes(b"x")
            rename_files({src / "a.mp4": "b.mp4"}, dst, db, "movie")
            rec = dict(db.history[0])
            results = rollback_records([rec], db, source_dir=src)
            self.assertFalse((dst / "b.mp4").exists())
            self.assertTrue((src / "a.mp4").exists())
            self.assertEqual(results[0]["status"], "已回滚")
            self.assertEqual(db.history, [])

    def test_scan_videos_exclude_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "new").mkdir()
            (root / "new" / "a.mp4").write_bytes(b"x")
            (root / "new2").mkdir()
            (root / "new2" / "b.mp4").write_bytes(b"x")
            files = scan_videos(root, exclude_dirs=["new"])
            names = sorted(f.name for f in files)
            self.assertEqual(names, ["b.mp4"])  # new2 不应被误排除

    def test_rename_files_creates_target(self):
        db = FakeDB()
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "from"
            dst = Path(d) / "to" / "deep"  # 目标目录不存在
            src.mkdir()
            (src / "a.mp4").write_bytes(b"x")
            records = rename_files({src / "a.mp4": "b.mp4"}, dst, db, "movie")
            self.assertEqual(records[0]["status"], "成功")
            self.assertTrue((dst / "b.mp4").exists())

    def test_rename_batch_id_grouped_per_call(self):
        db = FakeDB()
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "from"
            dst = Path(d) / "to"
            src.mkdir()
            dst.mkdir()
            (src / "a1.mp4").write_bytes(b"1")
            (src / "a2.mp4").write_bytes(b"2")
            (src / "a3.mp4").write_bytes(b"3")
            rename_files({src / "a1.mp4": "b1.mp4", src / "a2.mp4": "b2.mp4"}, dst, db, "movie")
            rename_files({src / "a3.mp4": "b3.mp4"}, dst, db, "movie")
            ids = {r["batch_id"] for r in db.history}
            self.assertEqual(len(ids), 2)  # 两次调用两个批次
            first_batch = [r for r in db.history if r["old_name"] in ("a1.mp4", "a2.mp4")]
            self.assertEqual(len({r["batch_id"] for r in first_batch}), 1)

    def test_rollback_conflict_non_destructive(self):
        db = FakeDB()
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "from"
            dst = Path(d) / "to"
            src.mkdir()
            dst.mkdir()
            (src / "a.mp4").write_bytes(b"x")
            rename_files({src / "a.mp4": "b.mp4"}, dst, db, "movie")
            (src / "a.mp4").write_bytes(b"conflicting")  # 目标名已被占用
            rec = dict(db.history[0])
            results = rollback_records([rec], db, source_dir=src)
            # 原占用文件保留，回滚文件追加序号，而非覆盖删除
            self.assertEqual((src / "a.mp4").read_bytes(), b"conflicting")
            self.assertTrue((src / "a_1.mp4").exists())
            self.assertEqual(results[0]["status"], "已回滚")


# ==================== profiles ====================

class TestProfiles(unittest.TestCase):
    def test_apply_rules(self):
        rules = {"4k": "2160p", ".mkv": ""}
        self.assertEqual(_apply_rules("movie.4k.mkv", rules), "movie.2160p")

    def test_homework_normalize(self):
        mgr = FakeConfigMgr(
            {"naming_rules": {"pattern": r"^(.*?)[\-_\.\s]+(.*)$",
                              "replacement": r"\1 - \2"}}
        )
        h = HomeworkHandler(None, mgr)
        files = [Path("CS101_Intro.mp4")]
        result = h.normalize(files)
        self.assertEqual(result[files[0]], "CS101 - Intro.mp4")

    def test_homework_normalize_no_replacement_preserves(self):
        mgr = FakeConfigMgr({"naming_rules": {"pattern": r"^(.*)$"}})
        h = HomeworkHandler(None, mgr)
        files = [Path("CS101_Intro.mp4")]
        self.assertEqual(h.normalize(files)[files[0]], "CS101_Intro.mp4")


# ==================== workspaces._shared ====================

class TestWorkspacesShared(unittest.TestCase):
    def test_parse_naming_rules(self):
        self.assertEqual(shared.parse_naming_rules(""), {})
        self.assertEqual(shared.parse_naming_rules('{"a":"b"}'), {"a": "b"})

    def test_parse_table_schema_invalid(self):
        self.assertEqual(shared.parse_table_schema(""), [])
        with self.assertRaises(ValueError):
            shared.parse_table_schema('{"name":"x"}')  # 非数组
        with self.assertRaises(ValueError):
            shared.parse_table_schema('[{"type":"TEXT"}]')  # 缺 name

    def test_save_config_writes_all(self):
        class Mgr:
            def __init__(self):
                self.saved = {}

            def update_profile_config(self, profile, key, value):
                self.saved[key] = value

        mgr = Mgr()
        err = shared.save_config(
            mgr, "movie", "R", "F", "T", '{"a":"b"}',
            '[{"name":"year","type":"INTEGER"}]',
            '{"count":3,"moments":[60]}', '{}',
        )
        self.assertEqual(err, "")
        self.assertEqual(mgr.saved["naming_rules"], {"a": "b"})
        self.assertEqual(mgr.saved["table_schema"][0]["name"], "year")
        self.assertEqual(mgr.saved["screenshot_config"]["moments"], [60])

    def test_save_config_bad_json_returns_error(self):
        err = shared.save_config(
            object(), "movie", "R", "F", "T", "{bad", "[]", "{}", "{}"
        )
        self.assertIn("命名规则 JSON 格式错误", err)


# ==================== config_manager ====================

class TestConfigManager(unittest.TestCase):
    def test_load_defaults_and_switch(self):
        with tempfile.TemporaryDirectory() as d:
            cm = ConfigManager(Path(d) / "cfg.json")
            self.assertIn("movie", cm.list_profiles())
            cm.current_profile = "tv"
            self.assertEqual(cm.current_profile, "tv")
            cm.update_profile_config("tv", "root", "/x")
            self.assertEqual(cm.get_profile_root("tv"), "/x")

    def test_switch_unknown_profile_raises(self):
        with tempfile.TemporaryDirectory() as d:
            cm = ConfigManager(Path(d) / "cfg.json")
            with self.assertRaises(ValueError):
                cm.current_profile = "nope"


# ==================== tools.cipher ====================

class TestCipher(unittest.TestCase):
    def test_roundtrip(self):
        text = "Hello世界！日本語とEnglish。Привет!"
        enc = cipher(text, key=42, encrypt=True)
        self.assertNotEqual(enc, text)
        self.assertEqual(cipher(enc, key=42, encrypt=False), text)

    def test_unknown_chars_preserved(self):
        self.assertEqual(cipher("\u0001\t", key=5), "\u0001\t")


class TestDatabase(unittest.TestCase):
    def _db(self):
        d = tempfile.mkdtemp()
        db = Database(Path(d) / "test.db")
        db.create_tables()
        return db

    def test_upsert_preserves_cover_on_conflict(self):
        db = self._db()
        db.create_media_table("movie", [{"name": "year", "type": "INTEGER"}])
        db.upsert_media(profile="movie", title="t", mv_path="/m/a.mp4",
                        cover=b"COVER", year=2020)
        db.upsert_media(profile="movie", title="t", mv_path="/m/a.mp4",
                        year=2021)  # 不带 cover 的重复 upsert
        row = db.fetchone("SELECT cover, year, id FROM media_movie WHERE mv_path=?", ("/m/a.mp4",))
        self.assertEqual(row["cover"], b"COVER")  # cover 被保留
        self.assertEqual(row["year"], 2021)  # 新值已更新
        db.close()

    def test_migrate_adds_new_column(self):
        db = self._db()
        db.create_media_table("movie", [{"name": "year", "type": "INTEGER"}])
        # 配置页新增一列后再次调用，应补齐而非报错
        db.create_media_table("movie", [{"name": "year", "type": "INTEGER"},
                                        {"name": "duration", "type": "REAL"}])
        cols = db.get_media_columns("movie")
        self.assertIn("year", cols)
        self.assertIn("duration", cols)
        db.close()

    def test_get_last_batch_groups_by_batch_id(self):
        db = self._db()
        db.add_rename_history("a1.mp4", "b1.mp4", "/m", "movie", batch_id="B1")
        db.add_rename_history("a2.mp4", "b2.mp4", "/m", "movie", batch_id="B1")
        db.add_rename_history("a3.mp4", "b3.mp4", "/m", "movie", batch_id="B2")
        batch = db.get_last_batch("movie")
        self.assertEqual([r["old_name"] for r in batch], ["a3.mp4"])  # 仅 B2，不会合并 B1
        db.close()


if __name__ == "__main__":
    unittest.main()

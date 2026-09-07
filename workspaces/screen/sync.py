"""影视业务 — 同步后端。

实际逻辑委托 core/sync.py（diff_db/sync_db）、core/files.py、core/screenshots.py。
本模块作为 screen workspace 的同步后端入口，便于后续影视特有逻辑扩展。
"""
from core.sync import diff_db, sync_db, build_db

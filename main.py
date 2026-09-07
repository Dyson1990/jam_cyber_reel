"""CyberReel 主入口 — 初始化核心组件并启动 NiceGUI 应用。"""

import sys
from pathlib import Path

from nicegui import ui

from config_manager import ConfigManager
from core.db import Database
from profiles import ProfileRegistry
from ui.layout import create_layout
import ui.state as state

BASE = Path(__file__).parent

config_mgr = ConfigManager(BASE / "profiles_config.json")
db = Database(BASE / "data.db")
db.create_tables()
db.ensure_all_media_tables(config_mgr)

registry = ProfileRegistry(BASE / "profiles", db, config_mgr)
registry.discover()

# -testing-env 启动参数：区域名标签改为白色可见，便于定位调试
if "-testing-env" in sys.argv:
    state.TESTING_ENV = True


@ui.page("/")
def index():
    create_layout(config_mgr, db, registry)


ui.run(
    host="127.0.0.1",
    port=8080,
    title="CyberReel",
    reload="-reload" in sys.argv,
)

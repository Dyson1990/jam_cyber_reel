"""CyberReel 主入口 — 初始化核心组件并启动 NiceGUI 应用。"""

import sys
from pathlib import Path

from nicegui import ui

from config_manager import ConfigManager
from core.db import Database
from profiles import ProfileRegistry
from ui.layout import create_layout
import ui.state as state

# 全局赛博朋克霓虹主题（StyleKit cyberpunk-neon）：暗色纵向渐变 + 霓虹网格 + 扫描线 + 切角 HUD 面板 + 分层霓虹光晕
ui.add_head_html("""
<style>
html, body {
  background-color: #080818 !important;
  background-image: linear-gradient(to bottom, #0a0a14 0%, #141131 55%, #1a0a2e 100%);
  background-attachment: fixed;
}
/* 霓虹透视网格：上密下疏，向地平线淡出 */
body::before {
  content: "";
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background-image:
    linear-gradient(rgba(45, 226, 230, .06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(45, 226, 230, .06) 1px, transparent 1px);
  background-size: 40px 40px;
  -webkit-mask-image: linear-gradient(#000 25%, transparent 92%);
  mask-image: linear-gradient(#000 25%, transparent 92%);
}
/* 扫描线：约 3% 不透明度，置顶形成 CRT 质感，不拦截点击 */
body::after {
  content: "";
  position: fixed; inset: 0; z-index: 9999; pointer-events: none;
  background: repeating-linear-gradient(to bottom,
    transparent 0, transparent 3px, rgba(0, 0, 0, .03) 3px, rgba(0, 0, 0, .03) 4px);
}
.glow-text { text-shadow: 0 0 8px rgba(0, 240, 255, .7), 0 0 22px rgba(0, 240, 255, .35); }
/* 霓虹灯招牌：白热灯芯 + 多层青色光晕 + 偶发微闪 */
.neon-title {
  color: #e0fbff;
  font-weight: 700;
  text-shadow:
    0 0 4px #ffffff,
    0 0 10px #00f0ff,
    0 0 22px #00f0ff,
    0 0 44px #00f0ff,
    0 0 80px #00f0ff;
  animation: neon-flicker 5s infinite;
}
@keyframes neon-flicker {
  0%, 89%, 93%, 100% { opacity: 1; }
  90% { opacity: .6; }
  91% { opacity: .95; }
  94% { opacity: .8; }
  95% { opacity: 1; }
}
.nicegui-header {
  background: rgba(10, 10, 24, .78) !important;
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(45, 226, 230, .35) !important;
  box-shadow: 0 0 18px rgba(45, 226, 230, .15);
}
.nicegui-drawer {
  background: #0c0c20 !important;
  border-right: 1px solid rgba(45, 226, 230, .3) !important;
}
/* 卡片：去圆角 + 玻璃拟态 + 霓虹描边（静止 30% 光晕） */
.nicegui-card {
  background: rgba(20, 20, 42, .5) !important;
  backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
  border: 1px solid rgba(45, 226, 230, .3) !important;
  border-radius: 0 !important;
  box-shadow: 0 0 12px rgba(45, 226, 230, .12), inset 0 0 24px rgba(45, 226, 230, .04);
}
/* 按钮：去圆角 + 0.4s 过渡，悬停叠加分层霓虹光晕（80%） */
.q-btn {
  border-radius: 0 !important;
  transition: box-shadow .4s ease, background-color .4s ease, color .4s ease;
}
.q-btn:hover {
  box-shadow: 0 0 8px currentColor, 0 0 22px currentColor;
}
/* 输入/下拉框去圆角，保持切角 HUD 一致 */
.q-field__control, .q-field__control-container,
.q-field--outlined .q-field__control {
  border-radius: 0 !important;
}
.q-select .q-field__control { border-radius: 0 !important; }
</style>
""", shared=True)

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

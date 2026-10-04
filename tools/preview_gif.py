"""生成项目预览 GIF：跑起应用 → Playwright 逐页截图 → Pillow 合成。

用法（仓库根目录，用 venv 的 python）：
    .venv/Scripts/python.exe tools/preview_gif.py

产物：仓库根目录 preview.gif；临时帧存 preview_frames/（结束自动清理）。
"""

import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parent.parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
URL = "http://127.0.0.1:8080/"
FRAMES_DIR = ROOT / "preview_frames"
OUT_GIF = ROOT / "preview.gif"

# 页面顺序：按钮文本 → 帧文件名 → 页面标题（等待其可见再截图，避免点太快截到上一页）
PAGES = [
    (None, "home", "◆ HOME"),
    ("概览", "overview", "◆ 概览"),
    ("扫描", "scan", "◆ 扫描"),
    ("知识库", "kb", "◆ 知识库"),
    ("标准化", "normalize", "◆ 标准化"),
    ("截图", "screenshot", "◆ 截图"),
    ("字幕", "subtitle", "◆ 配字幕"),
]

VIEWPORT = {"width": 1440, "height": 900}
SETTLE_MS = 200          # 标题出现后额外缓冲，等字体/光晕落位
GIF_WIDTH = 1000         # 合成帧统一宽度
GIF_DURATION = 1400      # 每帧停留 ms


def _wait_ready(timeout: float = 40.0) -> None:
    """轮询直到应用返回 200，超时抛错（常见原因：8080 已被占用）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(URL, timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise TimeoutError(f"应用未在 {timeout}s 内就绪（检查 8080 是否被占用）")


def _shot(page, name: str) -> Path:
    """当前视口截图到帧文件。"""
    path = FRAMES_DIR / f"{name}.png"
    page.screenshot(path=str(path))
    return path


def _compose(frames: list[Path]) -> None:
    """等比缩放到 GIF_WIDTH 并合成无限循环 GIF。"""
    imgs = []
    for p in frames:
        im = Image.open(p).convert("RGB")
        ratio = GIF_WIDTH / im.width
        im = im.resize((GIF_WIDTH, round(im.height * ratio)), Image.LANCZOS)
        imgs.append(im)
    imgs[0].save(
        OUT_GIF, save_all=True, append_images=imgs[1:],
        duration=GIF_DURATION, loop=0, optimize=True,
    )


def main() -> int:
    from playwright.sync_api import sync_playwright

    shutil.rmtree(FRAMES_DIR, ignore_errors=True)
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        [str(VENV_PY), "main.py"], cwd=str(ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    frames: list[Path] = []
    try:
        _wait_ready()
        with sync_playwright() as pw:
            # 复用系统已装的 Chrome/Edge，免下载 playwright 自带 chromium（下载极慢）
            browser = pw.chromium.launch(channel="chrome")
            ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
            page = ctx.new_page()
            page.goto(URL)
            page.get_by_text("CYBERREEL").first.wait_for(timeout=20000)

            for btn_text, name, title in PAGES:
                if btn_text:
                    # 菜单按钮文本含图标前缀，用正则部分匹配「中文标签」
                    page.get_by_role("button", name=re.compile(btn_text)).first.click()
                # 等目标页标题真正渲染出来（exact 避免「知识库」误配「知识库扩充」等）
                page.get_by_text(title, exact=True).first.wait_for(
                    state="visible", timeout=15000,
                )
                page.wait_for_timeout(SETTLE_MS)
                frames.append(_shot(page, name))
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    _compose(frames)
    shutil.rmtree(FRAMES_DIR, ignore_errors=True)
    print(f"OK: {OUT_GIF}  ({len(frames)} 帧)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

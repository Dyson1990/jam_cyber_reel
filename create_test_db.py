"""
一次性测试数据库初始化脚本。

文件作用：
    创建 data.db、建表、写入最少测试数据。
    所有测试数据均由 Python 本地随机生成（random / uuid / Pillow）。

与其它模块的关系：
    - 使用 core/db.py 的 Database 类操作数据库
    - 独立运行，不依赖 UI 或其他模块
    - 仅需执行一次，后续 main.py 可直接使用已有 data.db

禁止：
    - Base64 编码
    - 网络图片
    - 外部数据源
    - 大量测试数据

使用方法：
    python create_test_db.py
"""

import io
import random
import uuid
from pathlib import Path

from PIL import Image, ImageDraw

from core.db import Database
from config_manager import ConfigManager

# 项目根目录（脚本所在目录）
PROJECT_ROOT = Path(__file__).parent
DB_PATH = PROJECT_ROOT / "data.db"
CONFIG_PATH = PROJECT_ROOT / "profiles_config.json"


def generate_cover(width: int = 120, height: int = 160) -> bytes:
    """使用 Pillow 随机生成封面图片。

    生成赛博朋克风格的渐变色块图片，
    每条记录独立生成，确保不重复。

    Args:
        width: 图片宽度
        height: 图片高度

    Returns:
        PNG 格式的图片字节数据
    """
    r1, g1, b1 = random.randint(0, 80), random.randint(0, 255), random.randint(0, 255)
    r2, g2, b2 = random.randint(200, 255), random.randint(0, 100), random.randint(0, 255)

    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    for y in range(height):
        t = y / height
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # 随机添加装饰线条（模拟赛博朋克风格）
    for _ in range(random.randint(3, 8)):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = min(x1 + random.randint(-30, 30), width)
        y2 = min(y1 + random.randint(-30, 30), height)
        draw.line(
            [(x1, y1), (x2, y2)],
            fill=(0, 240, 255),
            width=random.randint(1, 2),
        )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def create_test_data(db: Database, config_mgr: ConfigManager) -> None:
    """写入测试数据到各 Profile 的 media 表和 rename_history 表。

    每类 Profile 写入 2-3 条随机记录，
    每条记录包含随机生成的标题、路径和封面。

    Args:
        db: Database 实例
        config_mgr: ConfigManager 实例
    """
    directors = ["Christopher Nolan", "Denis Villeneuve", "Ridley Scott", "James Cameron",
                  "Steven Spielberg", "David Fincher", "Quentin Tarantino", ""]
    series_list = ["Season 1", "Season 2", "Trilogy", "Collection", ""]
    codecs = ["H.264", "H.265", "AV1", "VP9", ""]
    resolutions = ["1920x1080", "3840x2160", "1280x720", ""]

    test_data = {
        "movie": [
            ("Blade Runner 2049", "D:/Media/Movies"),
            ("The Matrix Resurrections", "D:/Media/Movies"),
            ("Ghost in the Shell", "D:/Media/Movies/SciFi"),
        ],
        "tv": [
            ("Altered Carbon S01E01", "D:/Media/TV"),
            ("Cyberpunk Edgerunners E01", "D:/Media/TV"),
        ],
        "realshot": [
            ("DJI_20240501_153021", "D:/Media/RealShot"),
            ("GoPro_Hero12_20240515", "D:/Media/RealShot/2024"),
        ],
        "homework": [
            ("CS229_Lecture01_Intro", "D:/Media/Homework"),
            ("MIT_6.824_Lab1_MapReduce", "D:/Media/Homework"),
        ],
    }

    for profile, items in test_data.items():
        for title, folder in items:
            ext = random.choice([".mp4", ".mkv", ".avi", ".mov"])
            mv_path = f"{folder}/{title}{ext}"

            # 根据 Profile 构建扩展列
            extra: dict = {}
            if profile == "movie":
                extra["director"] = random.choice(directors)
                extra["year"] = random.choice([2017, 2019, 2020, 2021, 2022, 2023, 2024, 0])
                extra["codec"] = random.choice(codecs)
                extra["resolution"] = random.choice(resolutions)
                extra["duration"] = random.uniform(3600, 9000)
            elif profile == "tv":
                extra["series"] = random.choice(series_list)
                extra["year"] = random.choice([2020, 2021, 2022, 2023, 2024, 0])
                extra["codec"] = random.choice(codecs)
                extra["resolution"] = random.choice(resolutions)
                extra["duration"] = random.uniform(1800, 3600)
            elif profile == "realshot":
                extra["codec"] = random.choice(codecs)
                extra["resolution"] = random.choice(resolutions)
                extra["duration"] = random.uniform(60, 1800)
            elif profile == "homework":
                extra["series"] = random.choice(["CS229", "MIT_6.824", "STATS216", ""])
                extra["duration"] = random.uniform(2400, 5400)

            extra["file_size"] = random.randint(500_000_000, 8_000_000_000)

            db.upsert_media(
                profile=profile,
                title=title,
                mv_path=mv_path,
                cover=generate_cover(),
                **extra,
            )

        # 为每个 Profile 写入 1-2 条重命名历史
        for _ in range(random.randint(1, 2)):
            fake_old = f"raw_{uuid.uuid4().hex[:8]}.mp4"
            fake_new = f"{random.choice([t for t, _ in items])}.mp4"
            db.add_rename_history(
                old_name=fake_old,
                new_name=fake_new,
                path=random.choice([d for _, d in items]),
                profile=profile,
            )


def main():
    """主入口：创建数据库、建表、写入测试数据。"""
    print(f"Creating database: {DB_PATH}")
    db = Database(DB_PATH)
    db.create_tables()

    # 加载配置以获取 table_schema，创建各 Profile 的媒体表
    config_mgr = ConfigManager(CONFIG_PATH)
    db.ensure_all_media_tables(config_mgr)

    create_test_data(db, config_mgr)
    db.close()
    print("Test data written successfully.")


if __name__ == "__main__":
    main()

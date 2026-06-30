"""列出指定目录下所有视频文件。"""
import sys
from pathlib import Path

VIDEO = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".ts"}


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    if not root.exists():
        print(f"路径不存在: {root}")
        return

    files = sorted(
        f for f in root.rglob("*")
        if f.suffix.lower() in VIDEO and f.is_file()
    )
    for f in files:
        print(f)
    print(f"\n共 {len(files)} 个视频文件")


if __name__ == "__main__":
    main()

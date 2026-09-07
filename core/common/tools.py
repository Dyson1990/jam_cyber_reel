"""工具页后端 — 脚本扫描与运行，不依赖 UI。"""

import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_TOOLS_DIR = _PROJECT_ROOT / "tools"


def list_scripts() -> list[Path]:
    """扫描 tools/ 目录，返回所有 .py 脚本路径。"""
    if not _TOOLS_DIR.exists():
        return []
    return sorted(
        f for f in _TOOLS_DIR.iterdir()
        if f.suffix == ".py" and not f.name.startswith("_")
    )


def run_script(script_path: Path, config_mgr, user_args: str = "") -> str:
    """运行脚本，返回 stdout/stderr 合并文本。

    参数区非空时作为 argv[1:]（空格分隔），否则用当前 Profile 的 root。
    """
    if user_args.strip():
        cmd = [sys.executable, str(script_path)] + user_args.strip().split()
    else:
        root = config_mgr.get_profile_root() or str(Path.cwd())
        cmd = [sys.executable, str(script_path), root]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace", env=env, cwd=str(_PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        return "运行超时（30秒）"
    except Exception as e:
        return f"运行失败: {e}"

    output = result.stdout
    if result.stderr:
        output += f"\n[stderr]\n{result.stderr}"
    return output.strip() or "(无输出)"

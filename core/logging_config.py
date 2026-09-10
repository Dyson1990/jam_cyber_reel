"""
日志系统 — 企业级分级日志：分级别落盘、每日轮转仅留 14 份、终端仅 WARNING+。

用法：
    from core.logging_config import get_logger
    logger = get_logger(__name__)
    logger.info(...) / logger.warning(...) / logger.error(...) / logger.exception(...)

文件布局（logs/，由 main.py 传入根目录）：
    app.log       全量（DEBUG+，主日志，用于完整还原现场）
    info.log      仅 INFO
    warning.log   仅 WARNING
    error.log     仅 ERROR 及以上（含 CRITICAL）
    每个文件每日轮转（backupCount=14），仅保留最近约 14 天。

设计理由：
    - 分级落盘：error.log 可直接 grep 定位异常，无需在主日志里过滤。
    - app.log 保留全量上下文，追查时按时间戳关联到 info/debug。
    - 终端只显示 WARNING+，避免 NiceGUI/第三方库的 INFO 刷屏。
"""

import logging
import sys
import threading
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
_CONSOLE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False
_log_dir: Path | None = None


class _LevelFilter(logging.Filter):
    """仅放行落在 [min_level, max_level] 级别区间内的记录（max 为 None 表示无上限）。"""

    def __init__(self, min_level: int, max_level: int | None = None):
        super().__init__()
        self.min_level = min_level
        self.max_level = max_level

    def filter(self, record) -> bool:
        if record.levelno < self.min_level:
            return False
        if self.max_level is not None and record.levelno > self.max_level:
            return False
        return True


def _file_handler(
    filename: str, level: int, filter_: _LevelFilter | None = None,
) -> TimedRotatingFileHandler:
    h = TimedRotatingFileHandler(filename, when="midnight", backupCount=14, encoding="utf-8")
    h.setLevel(level)
    h.setFormatter(logging.Formatter(_FORMAT, _DATE_FORMAT))
    if filter_ is not None:
        h.addFilter(filter_)
    return h


def setup_logging(log_dir: Path) -> None:
    """配置根 logger（幂等，重复调用不叠加 handler）。"""
    global _configured, _log_dir
    if _configured:
        return
    _log_dir = log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.WARNING)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT, _DATE_FORMAT))
    root.addHandler(console)

    # 全量主日志 + 分级别日志
    root.addHandler(_file_handler(str(log_dir / "app.log"), logging.DEBUG))
    root.addHandler(_file_handler(str(log_dir / "info.log"), logging.INFO, _LevelFilter(logging.INFO, logging.INFO)))
    root.addHandler(_file_handler(str(log_dir / "warning.log"), logging.WARNING, _LevelFilter(logging.WARNING, logging.WARNING)))
    root.addHandler(_file_handler(str(log_dir / "error.log"), logging.ERROR, _LevelFilter(logging.ERROR)))

    # watchfiles（reload 热重载）对每次文件变化都打 DEBUG「change detected」，
    # 该日志又写回 app.log，形成「检测→写日志→再检测」的死循环；抬高级别打断闭环
    logging.getLogger("watchfiles").setLevel(logging.WARNING)

    _configured = True


def install_excepthook() -> None:
    """把主线程与子线程的未捕获异常写入 error.log，便于定位「点了没反应」。"""

    def _hook(exc_type, exc_value, exc_tb):
        logging.getLogger("uncaught").critical(
            "主线程未捕获异常", exc_info=(exc_type, exc_value, exc_tb)
        )

    def _thread_hook(args: threading.ExceptHookArgs):
        logging.getLogger("uncaught").critical(
            "线程未捕获异常", exc_info=(args.exc_type, args.exc_value, args.exc_traceback)
        )

    sys.excepthook = _hook
    threading.excepthook = _thread_hook


def get_logger(name: str) -> logging.Logger:
    """返回具名 logger（传播到已配置的根 logger）。"""
    return logging.getLogger(name)


def get_log_dir() -> Path | None:
    """返回日志目录（供业务侧写入可检查的产物文件）。"""
    return _log_dir


def read_recent_logs(lines: int = 100, level: str | None = None) -> list[str]:
    """读取日志文件末尾 N 行（供首页运行日志面板展示）。

    level=None 读取全量 app.log；'info'/'warning'/'error' 读取对应分级文件。
    """
    if _log_dir is None:
        return []
    filename = "app.log" if level is None else f"{level}.log"
    path = _log_dir / filename
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.readlines()
    return [ln.rstrip("\n") for ln in content[-lines:]]

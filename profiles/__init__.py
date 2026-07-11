"""
Profile 插件架构核心 - 定义统一接口与 Profile 注册机制。

文件作用：
    1. 定义 ProfileBase 基类，包含 scan/rename/rollback/build_db 通用实现
    2. 提供 ProfileRegistry 实现插件发现与加载
    3. normalize() 留给各 Profile 自行实现（dict 映射 vs regex）

与其它模块的关系：
    - 所有 profiles/*/handler.py 继承 ProfileBase
    - main.py 通过 ProfileRegistry 加载全部 Profile
    - Sync 页面通过 Registry 获取 handler 实例执行同步

Profile 插件架构说明：
    每个 Profile 是一个独立目录，包含：
        config.py  - 默认配置（扩展名列表等）
        rules.py   - 命名规则（dict 映射或 regex 模式）
        handler.py - normalize() 实现

    新增媒体类型只需新增一个 Profile 目录，无需修改主程序。

    通用逻辑集中在 ProfileBase，避免各 Profile 重复代码：
        scan()     - rglob 扫描视频文件
        rename()   - 两阶段重命名（UUID 中转防冲突），支持跨目录移动
        rollback() - 按 rename_history 逐条回滚，支持跨目录还原
        build_db() - 遍历目录写入 media 表

主要类：
    ProfileBase     - 基类（通用逻辑 + 抽象 normalize）
    ProfileRegistry - 注册与发现中心
"""

import importlib
import os
import re
import uuid
from abc import ABC
from pathlib import Path
from typing import Optional

# 所有 Profile 通用的视频扩展名集合
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".ts"}


class ProfileBase(ABC):
    """所有 Profile handler 的基类。

    设计理由：
        将 scan/rename/rollback/build_db 的通用实现放在基类，
        子类只需实现 normalize()（dict 映射 vs regex），
        既保持插件独立性，又避免大量重复代码。
    """

    def __init__(self, db, config_manager):
        """初始化。

        Args:
            db: Database 实例
            config_manager: ConfigManager 实例
        """
        self.db = db
        self.config_manager = config_manager
        # profile_name 从模块路径自动提取：profiles.movie.handler → movie
        self.profile_name: str = self.__class__.__module__.split(".")[-2]

    @property
    def config(self) -> dict:
        """快捷获取当前 Profile 的配置字典。"""
        return self.config_manager.get_profile_config(self.profile_name)

    # ==================== scan（通用实现） ====================

    def scan(
        self,
        root_override: Optional[Path] = None,
        exclude_dirs: Optional[list[str]] = None,
    ) -> list[Path]:
        """递归扫描目录，收集所有视频文件。

        策略：
            使用 rglob 递归搜索，大小写不敏感匹配扩展名。

        Args:
            root_override: 覆盖配置中的 root 路径（用于扫描 new 文件夹等）
            exclude_dirs: 排除的子目录名列表（如 ["new"] 排除 root/new/）

        Returns:
            视频文件 Path 列表（已去重）
        """
        root = root_override or Path(self.config.get("root", ""))
        if not root or str(root) == ".":
            return []

        root_path = Path(root)
        if not root_path.exists():
            return []

        # 构建排除路径集合
        exclude_prefixes: list[str] = []
        if exclude_dirs:
            for d in exclude_dirs:
                p = os.path.normpath(str(root_path / d)).lower()
                exclude_prefixes.append(p)

        seen: set[str] = set()
        files: list[Path] = []
        for f in root_path.rglob("*"):
            if f.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            if f.is_dir():
                continue
            # 跳过排除目录下的文件（用 normpath 纯字符串比较，不访问文件系统）
            f_norm = os.path.normpath(str(f)).lower()
            if exclude_prefixes:
                if any(f_norm.startswith(ep) for ep in exclude_prefixes):
                    continue
            if f_norm not in seen:
                seen.add(f_norm)
                files.append(f)
        return files

    # ==================== normalize（抽象，子类实现） ====================

    def normalize(self, files: list[Path]) -> dict[Path, str]:
        """根据命名规则生成规范化文件名。

        默认实现：naming_rules 为 {"A": "B"} 格式的 dict 映射表，
        对每个文件名 stem 做 key→value 字符串替换。
        Homework 等需要 regex 的 Profile 可 override 此方法。

        Args:
            files: scan() 返回的文件列表

        Returns:
            {原路径: 规范化文件名（含扩展名，不含目录）}
        """
        naming_rules = self.config.get("naming_rules", {})
        result: dict[Path, str] = {}
        for f in files:
            name = f.name  # 含扩展名，与用户配置的 key 对齐
            for key, val in naming_rules.items():
                name = name.replace(key, val)
            result[f] = name
        return result

    # ==================== rename（通用实现：两阶段 UUID 策略） ====================

    def rename(
        self,
        mapping: dict[Path, str],
        target_dir: Optional[Path] = None,
    ) -> list[dict]:
        """执行两阶段重命名，记录到 rename_history。

        两阶段策略：
            第1阶段：全部文件 → UUID.扩展名（零冲突）
            第2阶段：UUID.扩展名 → 规范名

        target_dir 为 None 时原地重命名；
        指定 target_dir 时第2阶段将文件移动到目标目录。

        设计理由：
            直接重命名可能导致 A→B、C→A 的冲突链条，
            UUID 中转彻底消除此问题。

        Args:
            mapping: normalize() 返回的 {路径: 新文件名}
            target_dir: 目标目录（None=原地，指定=移动到此目录）

        Returns:
            操作记录列表
        """
        records: list[dict] = []

        # 阶段1：→ UUID（同目录内）
        temp: dict[Path, Path] = {}
        for old_path, new_name in mapping.items():
            parent = old_path.parent
            tmp_name = f"{uuid.uuid4().hex}{old_path.suffix}"
            tmp_dest = parent / tmp_name
            try:
                old_path.rename(tmp_dest)
                temp[old_path] = tmp_dest
            except OSError as e:
                records.append({
                    "old_name": old_path.name,
                    "new_name": new_name,
                    "path": str(parent),
                    "status": f"阶段1失败: {e}",
                })

        # 阶段2：UUID → 规范名（可选移动到 target_dir）
        for old_path, new_name in mapping.items():
            tmp_dest = temp.get(old_path)
            if tmp_dest is None:
                continue
            dest_dir = target_dir if target_dir else tmp_dest.parent
            final_dest = dest_dir / new_name
            # 同名保护
            if final_dest.exists() and final_dest != tmp_dest:
                stem = final_dest.stem
                c = 1
                while final_dest.exists():
                    final_dest = dest_dir / f"{stem}_{c}{final_dest.suffix}"
                    c += 1
            try:
                tmp_dest.rename(final_dest)
                actual_name = final_dest.name
                self.db.add_rename_history(
                    old_name=old_path.name,
                    new_name=actual_name,
                    path=str(dest_dir),
                    profile=self.profile_name,
                )
                records.append({
                    "old_name": old_path.name,
                    "new_name": actual_name,
                    "path": str(dest_dir),
                    "status": "成功",
                })
            except OSError as e:
                records.append({
                    "old_name": old_path.name,
                    "new_name": new_name,
                    "path": str(dest_dir),
                    "status": f"阶段2失败: {e}",
                })

        return records

    # ==================== rollback（通用实现） ====================

    def rollback_records(
        self, records: list, source_dir: Optional[Path] = None
    ) -> list[dict]:
        """回滚一批重命名记录。

        对每条记录：将文件从 path/new_name 移回 source_dir/old_name。
        source_dir 为 None 时移回原 path 目录。

        Args:
            records: rename_history 记录列表
            source_dir: 文件原始来源目录（如 from 目录）

        Returns:
            回滚结果列表
        """
        results: list[dict] = []
        for rec in records:
            cur = Path(rec["path"]) / rec["new_name"]
            orig_dir = source_dir or Path(rec["path"])
            orig = orig_dir / rec["old_name"]

            if cur.exists():
                try:
                    if orig.exists():
                        orig.unlink()
                    orig_dir.mkdir(parents=True, exist_ok=True)
                    cur.rename(orig)
                    self.db.delete_rename_history(rec["id"])
                    results.append({
                        "old_name": rec["new_name"],
                        "new_name": rec["old_name"],
                        "path": str(orig_dir),
                        "status": "已回滚",
                    })
                except OSError as e:
                    results.append({
                        "old_name": rec["new_name"],
                        "new_name": rec["old_name"],
                        "path": str(orig_dir),
                        "status": f"回滚失败: {e}",
                    })
            else:
                self.db.delete_rename_history(rec["id"])
                results.append({
                    "old_name": rec["new_name"],
                    "new_name": rec["old_name"],
                    "path": str(orig_dir),
                    "status": "文件已不存在，记录已清除",
                })
        return results

    def rollback_last_batch(
        self, source_dir: Optional[Path] = None
    ) -> list[dict]:
        """回滚最近一批（同一时间窗口内的全部记录）。"""
        batch = self.db.get_last_batch(self.profile_name)
        if not batch:
            return [{"status": "无历史记录可回滚"}]
        return self.rollback_records(batch, source_dir=source_dir)

    def rollback_date_range(
        self, start_date: str, end_date: str, source_dir: Optional[Path] = None
    ) -> list[dict]:
        """回滚指定日期范围内的全部记录。"""
        batch = self.db.get_rename_by_date_range(
            self.profile_name, start_date, end_date
        )
        if not batch:
            return [{"status": "日期范围内无记录"}]
        return self.rollback_records(batch, source_dir=source_dir)

    # ==================== build_db（通用实现） ====================

    def build_db(self) -> int:
        """扫描 Root 目录（排除 new/），将媒体文件信息写入 media 表。

        Returns:
            处理的文件数
        """
        root = self.config.get("root", "")
        if not root:
            return 0

        scan_path = Path(root)
        if not scan_path.exists():
            return 0

        count = 0
        for f in scan_path.iterdir():
            if not f.is_file() or f.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            self.db.upsert_media(
                profile=self.profile_name,
                title=f.stem,
                mv_path=str(f),
                file_size=f.stat().st_size,
            )
            count += 1
        return count

    # ==================== diff_db（数据库对比） ====================

    def diff_db(
        self, exclude_dirs: Optional[list[str]] = None
    ) -> dict:
        """扫描 Root 目录，与 media 表对比，返回增减清单。

        策略：
            1. scan() 获取 Root 下所有视频文件的绝对路径集合
            2. 从 media 表获取当前 Profile 已记录的 mv_path 集合
            3. 差集运算：added = 磁盘有但 DB 无，removed = DB 有但磁盘无

        Args:
            exclude_dirs: 排除的子目录名列表（如 ["new"]）

        Returns:
            {
                "added": [Path, ...],
                "removed": [str, ...],
                "existing": int,
            }
        """
        root = self.config.get("root", "")
        if not root:
            return {"added": [], "removed": [], "existing": 0}

        disk_files = self.scan(exclude_dirs=exclude_dirs)
        disk_set: set[str] = {os.path.normpath(str(f)) for f in disk_files}

        db_records = self.db.get_media_by_profile(self.profile_name)
        db_set: set[str] = {r["mv_path"] for r in db_records}

        added_paths = [Path(p) for p in disk_set - db_set]
        removed_paths = list(db_set - disk_set)
        existing = len(disk_set & db_set)

        return {
            "added": sorted(added_paths, key=lambda p: p.name),
            "removed": sorted(removed_paths),
            "existing": existing,
        }

    def sync_db(
        self, exclude_dirs: Optional[list[str]] = None
    ) -> int:
        """将当前 Root 中的文件同步到 media 表（排除指定子目录）。

        对 added 文件执行 upsert，对 removed 文件保留记录。

        Args:
            exclude_dirs: 排除的子目录名列表

        Returns:
            新增的记录数
        """
        diff = self.diff_db(exclude_dirs=exclude_dirs)
        count = 0
        for f in diff["added"]:
            if f.exists():
                self.db.upsert_media(
                    profile=self.profile_name,
                    title=f.stem,
                    mv_path=str(f),
                    file_size=f.stat().st_size,
                )
                count += 1
        return count


    # ==================== capture_screenshots（截图采集） ====================

    def capture_screenshots(self) -> list[dict]:
        """对当前 Profile 所有 DB 媒体记录截取视频帧。

        从 media 表读取 mv_path，逐个调用 capture_one_video()。
        时间点由 screenshot_config 决定：
            - moments 非空：按指定时间点（秒）截取
            - moments 为空：按 count 在视频时长内均匀分布

        Returns:
            [{mv_path, status, count}, ...]
        """
        cfg = self.config
        ss_cfg = cfg.get("screenshot_config", {})
        count = ss_cfg.get("count", 3)
        moments = ss_cfg.get("moments", [])

        records = self.db.get_media_by_profile(self.profile_name)
        if not records:
            return [{"status": "无媒体记录"}]

        results: list[dict] = []
        for rec in records:
            r = self.capture_one_video(rec["mv_path"], count, moments)
            results.append(r)
        return results

    def capture_one_video(
        self, mv_path: str, count: int = 3, moments: Optional[list] = None,
    ) -> dict:
        """对单个视频文件截取帧，存入 screenshots 表。

        截图数量已达 count 上限时跳过。
        moments 为空时对非指定时间点的随机截图做质量检查（<800KB 重试）。

        Args:
            mv_path: 视频文件路径
            count: 最多截取张数
            moments: 指定时间点列表（秒），非空时忽略 count

        Returns:
            {mv_path, status, count}
        """
        if moments is None:
            moments = []

        # 检查已有截图数量
        existing = self.db.fetchone(
            "SELECT COUNT(*) as cnt FROM screenshots WHERE mv_path=?",
            (mv_path,),
        )
        if existing and existing["cnt"] >= count:
            return {"mv_path": mv_path, "status": f"已有 {existing['cnt']} 张（上限 {count}）", "count": 0}

        video = Path(mv_path)
        if not video.exists():
            return {"mv_path": mv_path, "status": "文件不存在", "count": 0}

        try:
            time_points, duration = _resolve_time_points(video, moments, count)
        except Exception as e:
            return {"mv_path": mv_path, "status": f"无法打开视频: {e}", "count": 0}

        needs_quality = not moments  # 非指定时间点需要质量检查
        captured = 0
        for tp in time_points:
            # 再次检查是否已达上限（每次截取后更新）
            if captured >= count:
                break
            img_bytes = _extract_frame_pyav(video, tp)
            if img_bytes:
                # 质量检查：非指定时间点且 < 800KB，尝试找到更丰富的帧
                if needs_quality and len(img_bytes) < 800 * 1024:
                    alt = _retry_quality_frame(video, tp, duration)
                    if alt and len(alt) > len(img_bytes):
                        img_bytes = alt
                if img_bytes:
                    label = _format_time_label(tp)
                    self.db.add_screenshot(
                        mv_path=mv_path,
                        profile=self.profile_name,
                        image=img_bytes,
                        time_point=tp,
                        time_label=label,
                    )
                    captured += 1

        return {
            "mv_path": mv_path,
            "status": f"截取 {captured}/{len(time_points)} 张",
            "count": captured,
        }


# ==================== PyAV 帧提取辅助（模块级） ====================

def _resolve_time_points(
    video: Path, times: list, count: int,
) -> tuple[list[float], float]:
    """根据配置和视频时长确定截取时间点。

    Args:
        video: 视频文件路径
        times: 用户指定的时间点列表（秒）
        count: 默认截取张数

    Returns:
        ([时间点列表], 视频时长)
    """
    import av
    container = av.open(str(video))
    stream = container.streams.video[0]
    duration = float(stream.duration * stream.time_base) if stream.duration else 0.0
    container.close()

    if times:
        valid = [float(t) for t in times if 0 < float(t) < (duration or float("inf"))]
        return (valid if valid else [min(1.0, duration * 0.1)]), duration

    if duration and count > 0:
        step = duration / (count + 1)
        return [step * (i + 1) for i in range(count)], duration

    # 时长未知时，使用几何级数偏移量确保覆盖不同时间段
    fallback = [5.0, 30.0, 120.0, 600.0, 1800.0]
    return fallback[:count], duration


def _extract_frame_pyav(video: Path, time_sec: float) -> Optional[bytes]:
    """使用 PyAV 从视频指定时间点提取一帧，返回 PNG 字节。"""
    import av
    import io

    try:
        container = av.open(str(video))
    except Exception:
        return None

    try:
        stream = container.streams.video[0]
        if stream.duration is None and stream.frames == 0:
            container.close()
            return None

        seek_pts = int(time_sec / stream.time_base)
        # 确保 seek 目标不超过流末尾
        if stream.duration:
            max_pts = stream.duration - 1
            seek_pts = min(seek_pts, max_pts)
        container.seek(seek_pts, stream=stream)

        for frame in container.decode(stream):
            try:
                img = frame.to_image()
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                container.close()
                return buf.getvalue()
            except Exception:
                continue
    except Exception:
        pass
    finally:
        try:
            container.close()
        except Exception:
            pass
    return None


def _retry_quality_frame(
    video: Path, original_sec: float, duration: float, max_attempts: int = 5,
) -> Optional[bytes]:
    """质量不足时在相邻时间点重试截取。

    随机偏移原时间点重试，返回最大的有效帧（仅全部失败才返回 None）。
    对时长未知的视频使用更宽的偏移范围。

    Args:
        video: 视频文件路径
        original_sec: 原始时间点
        duration: 视频总时长
        max_attempts: 最大重试次数

    Returns:
        PNG 字节数据或 None
    """
    import random
    best = None
    best_size = 0
    for _ in range(max_attempts):
        if duration > 0:
            offset = random.uniform(-duration * 0.05, duration * 0.05)
        else:
            offset = random.uniform(-30.0, 30.0)
        new_sec = max(1.0, original_sec + offset)
        if duration > 0:
            new_sec = min(duration - 1.0, new_sec)
        img = _extract_frame_pyav(video, new_sec)
        if img and len(img) > best_size:
            best = img
            best_size = len(img)
            if best_size >= 800 * 1024:
                return best
    return best


def _format_time_label(seconds: float) -> str:
    """将秒数格式化为 HH:MM:SS 标签。

    Args:
        seconds: 秒数

    Returns:
        格式化的时间字符串
    """
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class ProfileRegistry:
    """Profile 注册中心。

    设计理由：
        自动扫描 profiles/ 目录发现所有 handler 模块，
        主程序无需硬编码 Profile 列表。
    """

    def __init__(self, profiles_path: Path, db, config_manager):
        self.profiles_path = profiles_path
        self.db = db
        self.config_manager = config_manager
        self._handlers: dict[str, ProfileBase] = {}

    def discover(self) -> dict[str, ProfileBase]:
        """扫描 profiles/ 子目录，动态加载所有 Profile handler。

        每个子目录必须包含 handler.py，
        其中定义一个继承 ProfileBase 的类。
        自动实例化并注册。

        Returns:
            {profile_name: handler 实例}
        """
        self._handlers.clear()
        for item in self.profiles_path.iterdir():
            if not item.is_dir() or item.name.startswith("_"):
                continue
            try:
                mod = importlib.import_module(
                    f"profiles.{item.name}.handler"
                )
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, ProfileBase)
                        and attr is not ProfileBase
                    ):
                        handler = attr(self.db, self.config_manager)
                        self._handlers[item.name] = handler
                        break
            except Exception as e:
                print(f"[Registry] {item.name} 加载失败: {e}")
        return self._handlers

    def get(self, name: str) -> Optional[ProfileBase]:
        return self._handlers.get(name)

    def list_names(self) -> list[str]:
        return list(self._handlers.keys())

    @property
    def handler_count(self) -> int:
        return len(self._handlers)

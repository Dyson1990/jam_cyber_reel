"""
截图采集 — PyAV 帧提取、质量检查、DB 存储。

公开函数（可直接测试，无需 DB）:
    resolve_time_points(video_path, count, moments) -> ([float], duration)
    extract_frame(video_path, time_sec) -> bytes | None
    extract_frames(video_path, time_points) -> [(time_sec, bytes), ...]
    format_time_label(seconds) -> str

公开函数（需 DB）:
    capture_one_video(db, mv_path, profile_name, count, moments) -> dict
    capture_screenshots(db, profile_name, config) -> list[dict]
"""

import io
import random
import time as _time
from pathlib import Path
from typing import Callable, Optional


# ==================== 纯函数（无需 DB，可直接测试） ====================

# av.open 共享选项：+genpts 强制重建时间戳，解决 MKV/HEVC 无索引时 seek 失败
ANALYZE_OPTS = {"fflags": "+genpts", "analyzeduration": "5000000"}


def _av_open(path: str, **kwargs):
    """av.open 包装：忽略元数据编码错误，兼容 GBK 等非 UTF-8 元数据。"""
    import av
    return av.open(path, metadata_errors='ignore', **kwargs)


def resolve_time_points(
    video_path: str, count: int = 3, moments: list | None = None,
    timeout: float = 30.0, cancel_fn: Callable[[], bool] | None = None,
) -> tuple[list[float], float]:
    """读取视频时长，计算截取时间点。

    Returns:
        ([时间点列表], 视频时长秒数)
    """
    import av
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

    if moments is None:
        moments = []

    def _do_probe() -> tuple[list[float], float]:
        container = _av_open(str(video_path), options=ANALYZE_OPTS)
        stream = container.streams.video[0]
        dur = float(stream.duration * stream.time_base) if stream.duration else 0.0
        container.close()

        if moments:
            valid = [float(t) for t in moments if 0 < float(t) < (dur or float("inf"))]
            return (valid if valid else [min(1.0, dur * 0.1)]), dur

        if dur and count > 0:
            step = dur / (count + 1)
            return [step * (i + 1) for i in range(count)], dur

        fallback = [5.0, 30.0, 120.0, 600.0, 1800.0]
        return fallback[:count], dur

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_do_probe)
            # 每 0.5s 轮询，支持取消
            deadline = _time.monotonic() + timeout
            while True:
                remain = deadline - _time.monotonic()
                if remain <= 0:
                    raise FutureTimeout
                try:
                    return future.result(timeout=min(0.5, remain))
                except FutureTimeout:
                    if cancel_fn and cancel_fn():
                        future.cancel()
                        return ([], 0.0)
    except FutureTimeout:
        raise TimeoutError(f"av.open 超时（>{timeout}s）")


def _frame_to_png(frame) -> Optional[bytes]:
    """单帧转 PNG 字节。to_image 失败时尝试多种 reformat 兜底。"""
    try:
        img = frame.to_image()
    except Exception:
        img = None
        # 按常见程度降序尝试：rgb24(8bit)、rgba、rgb48(10/12bit 需高位深)、bgr24
        for fmt in ["rgb24", "rgba", "bgr24", "yuv420p"]:
            try:
                img = frame.reformat(format=fmt).to_image()
                break
            except Exception:
                continue
        if img is None:
            return None
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def diagnose_video(video_path: str) -> dict:
    """诊断视频是否可正常解码，返回具体错误信息。"""
    import av
    result = {"ok": False, "has_video": False, "error": None, "codec": None}
    try:
        container = _av_open(str(video_path), options=ANALYZE_OPTS)
    except Exception as e:
        result["error"] = f"无法打开文件: {e}"
        return result
    try:
        if not container.streams.video:
            result["error"] = "无视频流"
            return result
        stream = container.streams.video[0]
        result["has_video"] = True
        result["codec"] = stream.codec_context.name if stream.codec_context else "?"
        result["duration"] = (
            float(stream.duration * stream.time_base) if stream.duration else 0.0
        )
        result["frames"] = stream.frames if stream.frames else 0
        # 尝试解码第一帧
        try:
            for frame in container.decode(stream):
                png = _frame_to_png(frame)
                if png:
                    result["ok"] = True
                    result["error"] = None
                else:
                    result["error"] = "帧转 PNG 失败（格式不支持）"
                break
            else:
                if result["error"] is None:
                    result["error"] = "无关键帧可解码"
        except Exception as e:
            result["error"] = f"解码异常: {e}"
    except Exception as e:
        result["error"] = f"探测异常: {e}"
    finally:
        try:
            container.close()
        except Exception:
            pass
    return result


def extract_frame(
    video_path: str, time_sec: float, timeout: float = 30.0,
    cancel_fn: Callable[[], bool] | None = None,
) -> Optional[bytes]:
    """从视频指定秒数提取一帧 PNG 字节。失败/超时返回 None。"""
    import av
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

    def _do_extract() -> Optional[bytes]:
        try:
            container = _av_open(str(video_path), options=ANALYZE_OPTS)
        except Exception:
            return None
        try:
            stream = container.streams.video[0]
            if not stream.time_base:
                return None
            seek_pts = int(time_sec / stream.time_base)
            if stream.duration:
                seek_pts = min(seek_pts, stream.duration - 1)
            if seek_pts < 0:
                seek_pts = 0

            # 策略1: keyframe seek（兼容性最好），取目标点之后最近的可解码帧
            container.seek(seek_pts, stream=stream, any_frame=False)
            best, best_dist = None, float("inf")
            for frame in container.decode(stream):
                dist = abs(frame.pts - seek_pts)
                if dist < best_dist:
                    img = _frame_to_png(frame)
                    if img:
                        best, best_dist = img, dist
                if frame.pts > seek_pts + int(2.0 / stream.time_base) and best is not None:
                    break
            if best:
                return best

            # 策略2: 精确 seek
            container.seek(seek_pts, stream=stream, any_frame=True)
            for frame in container.decode(stream):
                img = _frame_to_png(frame)
                if img:
                    return img
        except Exception:
            pass
        finally:
            try:
                container.close()
            except Exception:
                pass
        return None

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_do_extract)
            deadline = _time.monotonic() + timeout
            while True:
                remain = deadline - _time.monotonic()
                if remain <= 0:
                    return None
                try:
                    return future.result(timeout=min(0.5, remain))
                except FutureTimeout:
                    if cancel_fn and cancel_fn():
                        future.cancel()
                        return None
    except FutureTimeout:
        return None


def extract_frames(
    video_path: str, time_points: list[float],
) -> list[tuple[float, bytes]]:
    """从视频多个时间点提取帧，返回 [(time_sec, png_bytes), ...]。

    Args:
        video_path: 视频文件路径
        time_points: 时间点列表

    Returns:
        [(时间点, PNG字节), ...]（仅包含成功提取的帧）
    """
    results: list[tuple[float, bytes]] = []
    for tp in time_points:
        img = extract_frame(video_path, tp)
        if img:
            results.append((tp, img))
    return results


def retry_quality_frame(
    video_path: str, sec: float, duration: float, max_attempts: int = 5,
) -> Optional[bytes]:
    """质量不足时相邻时间点重试，返回最佳帧（≥800KB 则提前返回）。

    Args:
        video_path: 视频文件路径
        sec: 原始时间点
        duration: 视频时长（0 表示未知）
        max_attempts: 最大重试次数

    Returns:
        PNG 字节数据或 None
    """
    best, best_size = None, 0
    for _ in range(max_attempts):
        offset = (
            random.uniform(-duration * 0.05, duration * 0.05)
            if duration > 0 else random.uniform(-30.0, 30.0)
        )
        t = max(1.0, sec + offset)
        if duration > 0:
            t = min(duration - 1.0, t)
        img = extract_frame(video_path, t)
        if img and len(img) > best_size:
            best, best_size = img, len(img)
            if best_size >= 800 * 1024:
                return best
    return best


def format_time_label(seconds: float) -> str:
    """秒数 → HH:MM:SS 字符串。"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ==================== 编排函数（需 DB，组合上述纯函数） ====================

def capture_one_video(
    db, mv_path: str, profile_name: str,
    count: int = 3, moments: Optional[list] = None,
    cancel_fn: Callable[[], bool] | None = None,
) -> dict:
    """截取单视频帧并存入 screenshots 表。"""
    existing = db.get_screenshot_count(mv_path)
    if existing >= count:
        return {"mv_path": mv_path, "status": f"已有 {existing} 张（上限 {count}）", "count": 0}

    if not Path(mv_path).exists():
        return {"mv_path": mv_path, "status": "文件不存在", "count": 0}

    try:
        time_points, duration = resolve_time_points(mv_path, count, moments, cancel_fn=cancel_fn)
    except Exception as e:
        return {"mv_path": mv_path, "status": f"无法打开视频: {e}", "count": 0}

    if cancel_fn and cancel_fn():
        return {"mv_path": mv_path, "status": "已取消", "count": 0}

    needs_quality = not moments
    captured = 0
    failed_tps: list[float] = []
    for tp in time_points:
        if captured >= count:
            break
        if cancel_fn and cancel_fn():
            break
        img_bytes = extract_frame(mv_path, tp, cancel_fn=cancel_fn)
        if not img_bytes:
            failed_tps.append(tp)
            continue
        if needs_quality and len(img_bytes) < 800 * 1024:
            alt = retry_quality_frame(mv_path, tp, duration)
            if alt and len(alt) > len(img_bytes):
                img_bytes = alt
        db.add_screenshot(
            mv_path=mv_path, profile=profile_name,
            image=img_bytes, time_point=tp, time_label=format_time_label(tp),
        )
        captured += 1

    result = {
        "mv_path": mv_path,
        "count": captured,
    }

    # 全部失败时给出诊断信息
    if captured == 0 and failed_tps:
        diag = diagnose_video(mv_path)
        if diag["error"]:
            result["status"] = (
                f"截取 0/{len(time_points)} 张 — {diag['error']}"
                f"（codec={diag.get('codec') or '?'}）"
            )
        else:
            result["status"] = (
                f"截取 0/{len(time_points)} 张 — "
                f"视频可解码但 {len(failed_tps)} 个时间点 seek 均失败"
            )
    elif failed_tps:
        result["status"] = (
            f"截取 {captured}/{len(time_points)} 张"
            f"（{len(failed_tps)} 个时间点失败: {[format_time_label(t) for t in failed_tps]}）"
        )
    else:
        result["status"] = f"截取 {captured}/{len(time_points)} 张"

    return result


def capture_screenshots(db, profile_name: str, config: dict) -> list[dict]:
    """对 Profile 所有媒体记录截取视频帧。"""
    ss_cfg = config.get("screenshot_config", {})
    count = ss_cfg.get("count", 3)
    moments = ss_cfg.get("moments", [])

    records = db.get_media_by_profile(profile_name)
    if not records:
        return [{"status": "无媒体记录"}]

    results: list[dict] = []
    for rec in records:
        r = capture_one_video(db, rec["mv_path"], profile_name, count, moments)
        results.append(r)
    return results

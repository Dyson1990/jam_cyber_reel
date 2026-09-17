"""DTS 专利音轨检测（lab）。

移动端 OPlayer 等播放器报「需购买 DTS 专利授权」的根源：文件封装了 DTS 音轨
（FFmpeg 短编码名 dca = DCA / DTS Coherent Acoustics，覆盖 DTS core / DTS-HD MA /
DTS-HD HRA / DTS Express / DTS 96/24 等全部变体）。

检测方法：av.open 打开容器遍历音频流，按编码名 / 长名 / 规格任一含 dts 或 dca 判定。
"""

import av

_OPEN_OPTS = {"fflags": "+genpts", "analyzeduration": "5000000"}

_DTS_MARKERS = ("dts", "dca")


def _av_open(path: str):
    return av.open(path, metadata_errors="ignore", options=_OPEN_OPTS)


def _long_name(ctx) -> str:
    """长编码名走 ctx.codec.long_name（CodecContext 无 long_name 属性）。"""
    codec = getattr(ctx, "codec", None)
    return (getattr(codec, "long_name", None) or "") if codec else ""


def is_dts(codec_name: str, long_name: str, profile: str) -> bool:
    """判断一条音频流是否 DTS：编码名/长名/规格任一含 dts 或 dca。"""
    for field in (codec_name, long_name, profile):
        low = (field or "").lower()
        if any(m in low for m in _DTS_MARKERS):
            return True
    return False


def scan_audio_streams(path: str) -> dict:
    """读取文件全部音频流，返回 {has_dts, streams:[{codec,long_name,profile,
    channels,sample_rate,language,is_dts}]}。"""
    container = _av_open(path)
    try:
        streams = []
        for s in container.streams.audio:
            ctx = s.codec_context
            name = (ctx.name or "") if ctx else ""
            long_name = _long_name(ctx) if ctx else ""
            profile = (getattr(ctx, "profile", None) or "") if ctx else ""
            streams.append({
                "codec": name,
                "long_name": long_name,
                "profile": profile,
                "channels": (getattr(ctx, "channels", None) or 0) if ctx else 0,
                "sample_rate": (getattr(ctx, "sample_rate", None) or 0) if ctx else 0,
                "language": (s.metadata or {}).get("language", ""),
                "is_dts": is_dts(name, long_name, profile),
            })
        return {"has_dts": any(x["is_dts"] for x in streams), "streams": streams}
    finally:
        container.close()


def detect_file(path: str) -> dict:
    """单文件检测，返回 {path, has_dts, streams, error}。error 非 None 表示打开失败。"""
    try:
        data = scan_audio_streams(path)
    except Exception as e:
        return {"path": path, "has_dts": False, "streams": [], "error": str(e)}
    data["path"] = path
    data["error"] = None
    return data

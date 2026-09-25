"""媒体流探测（PyAV）— 从视频文件读技术槽位，供命名组装使用。

与 ai_slots.py（提示词）、naming.py（拼装）隔离：这里只做「读流 → 槽位值」，不掺任何提示词/命名逻辑。
probe() 一次 av.open 取全量，失败返回空 dict（缺失槽位由调用方按可空处理，不阻断）。
"""

from pathlib import Path

import av

# 分辨率阈值：宽 >= 3840/1920/1280 → 2160p/1080p/720p，更小不写（旧片源无意义）
_RES = ((3840, "2160p"), (1920, "1080p"), (1280, "720p"))

# 视频编码名归一（h264/hevc 是 ffmpeg 内部名，命名约定用 x264/x265）
_VIDEO_CODEC = {"h264": "x264", "avc": "x264", "hevc": "x265", "h265": "x265"}

# 音频编码名归一：aac/dca/truehd 等 ffmpeg 名 → 命名常用大写缩写
_AUDIO_CODEC = {
    "aac": "AAC", "ac3": "AC3", "eac3": "EAC3",
    "dca": "DTS", "dts": "DTS", "truehd": "TrueHD",
    "flac": "FLAC", "opus": "Opus", "vorbis": "Vorbis", "mp3": "MP3",
}

# 声道数 → 命名（6=5.1、8=7.1 等常见值；其余按 n.0）
_CHANNELS = {1: "1.0", 2: "2.0", 6: "5.1", 8: "7.1"}

# DTS 专利音轨判定标记（沿用 lab/dts：编码名/长名/规格任一含 dts/dca 即判 DTS）
_DTS_MARKERS = ("dts", "dca")

# 字幕流语言归类：只关注中文与英文，其余（含纯英文）一律「其他字幕」
_ZH = {"chi", "zho", "zh", "chs", "cht", "zhs", "zht", "cmn", "yue", "zh-hans", "zh-hant"}
_EN = {"eng", "en", "en-us", "en-gb"}


def _lang_code(s) -> str:
    """字幕流 language → 归一码（小写去前后缀），非字符串返回空。"""
    v = getattr(s, "language", None)
    return str(v or "").strip().lower()


def _video_slot(v) -> tuple[str, str, str, str]:
    """首个视频流 → (resolution, codec, bitdepth, hdr)。"""
    cc = v.codec_context
    w = getattr(cc, "width", 0) or 0
    resolution = next((r for n, r in _RES if w >= n), "")
    codec = _VIDEO_CODEC.get((getattr(cc, "name", "") or "").lower(),
                             (getattr(cc, "name", "") or "").lower())
    fmt = getattr(cc, "format", None) or getattr(cc, "pix_fmt", None)
    fmt_name = getattr(fmt, "name", None) or str(fmt or "")
    # >8bit 像素格式名带 10/12 标记（yuv420p10le / p012le）；8bit 无标记故兜底 8bit；
    # nv12 是 8bit 却含 "12"，单独排除。读不到 fmt_name 才留空（不臆断）。
    if fmt_name:
        if "10" in fmt_name:
            bitdepth = "10bit"
        elif "12" in fmt_name and "nv12" not in fmt_name:
            bitdepth = "12bit"
        else:
            bitdepth = "8bit"
    else:
        bitdepth = ""
    hdr = _hdr(cc)
    return resolution, codec, bitdepth, hdr


def _hdr(cc) -> str:
    """HDR：PQ 曲线(color_trc=2084)→HDR10；否则看 extradata 里的 Dolby Vision 配置块。"""
    trc = str(getattr(cc, "color_trc", None) or "").lower()
    if "2084" in trc or "pq" in trc:
        return "HDR10"
    ext = getattr(cc, "extradata", b"") or b""
    if b"DOVI" in ext or b"dovi" in ext:
        return "DV"
    return ""


def _audio_slot(a) -> tuple[str, str]:
    """音频流 → (audio_codec, channels)。"""
    cc = a.codec_context
    name = (getattr(cc, "name", "") or "").lower()
    codec = _AUDIO_CODEC.get(name, name)
    n = getattr(cc, "channels", 0) or 0
    channels = _CHANNELS.get(n, f"{n}.0") if n else ""
    return codec, channels


def _audio_is_dts(a) -> bool:
    """音频流是否 DTS：编码名/长名/规格任一含 dts/dca（沿用 lab/dts 判定）。"""
    cc = a.codec_context
    codec = getattr(cc, "codec", None)
    fields = (
        getattr(cc, "name", "") or "",
        getattr(codec, "long_name", "") if codec else "",
        getattr(cc, "profile", "") or "",
    )
    low = " ".join(fields).lower()
    return any(m in low for m in _DTS_MARKERS)


def _sub_slot(subs) -> str:
    """字幕流集合 → 中文字幕/中英双字/其他字幕/无字幕。

    双字=同时有中文与英文字幕流；仅中文=中文字幕；其余（纯英/其它语种）一律其他字幕。
    """
    codes = {_lang_code(s) for s in subs}
    codes.discard("")
    if not codes:
        return "无字幕"
    has_zh = bool(codes & _ZH)
    has_en = bool(codes & _EN)
    if has_zh and has_en:
        return "中英双字"
    if has_zh:
        return "中文字幕"
    return "其他字幕"


def probe(path: Path) -> dict:
    """读媒体流 → {resolution, codec, bitdepth, hdr, dts, audio_codec, channels, audio_tracks, sub}。

    值均为字符串，缺省为空串；失败返回空 dict（不抛错，命名缺失槽位按可空跳过）。
    """
    try:
        c = av.open(str(path), metadata_errors="ignore")
    except Exception:
        return {}
    try:
        info: dict = {}
        videos = c.streams.video or []
        if videos:
            info["resolution"], info["codec"], info["bitdepth"], info["hdr"] = _video_slot(videos[0])
        audios = c.streams.audio or []
        if audios:
            info["audio_codec"], info["channels"] = _audio_slot(audios[0])
        if len(audios) > 1:
            info["audio_tracks"] = "2AUDIO"
        if any(_audio_is_dts(a) for a in audios):
            info["dts"] = "【DTS】"
        info["sub"] = _sub_slot(c.streams.subtitles or [])
        return info
    finally:
        c.close()

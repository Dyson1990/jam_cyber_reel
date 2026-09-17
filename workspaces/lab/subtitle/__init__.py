"""字幕提取（lab）— 读取视频封装的字幕流并转 SRT。

文本字幕（subrip/ass/ssa/webvtt/mov_text 等）解码后转 SRT；图形字幕
（PGS/VobSub/DVB）无法直接出文字，仅标注类型。

解码用 codec_context.decode2()（返回带时间的 SubtitleSet），container.decode()
只吐 rect、丢失时间。时间换算：FFmpeg AVSubtitle.pts 单位微秒（AV_TIME_BASE），
start/end_display_time 单位毫秒（相对 pts）→ 绝对秒 = (pts + display*1000) / 1e6。
"""

import av

_OPEN_OPTS = {"fflags": "+genpts", "analyzeduration": "5000000"}
_AV_TIME_BASE = 1_000_000

_TEXT_CODECS = {
    "subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text",
    "microdvd", "jacosub", "mpl2", "pjs", "realtext", "sami",
    "subviewer", "subviewer1", "stl", "vplayer", "ttml",
    "eia_608", "cc_dec", "hdmv_text_subtitle",
}
_BITMAP_CODECS = {
    "hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub", "dvb_teletext",
}


def _av_open(path: str):
    return av.open(path, metadata_errors="ignore", options=_OPEN_OPTS)


def _long_name(ctx) -> str:
    codec = getattr(ctx, "codec", None)
    return (getattr(codec, "long_name", None) or "") if codec else ""


def _kind(codec_name: str) -> str:
    n = (codec_name or "").lower()
    if n in _BITMAP_CODECS:
        return "bitmap"
    if n in _TEXT_CODECS:
        return "text"
    return "unknown"


def list_subtitle_streams(path: str) -> list[dict]:
    """列出文件的全部字幕流，返回 [{pos,index,codec,long_name,language,kind}]。"""
    container = _av_open(path)
    try:
        out = []
        for pos, s in enumerate(container.streams.subtitles):
            ctx = s.codec_context
            name = (ctx.name or "") if ctx else ""
            out.append({
                "pos": pos,
                "index": s.index,
                "codec": name,
                "long_name": _long_name(ctx) if ctx else "",
                "language": (s.metadata or {}).get("language", ""),
                "kind": _kind(name),
            })
        return out
    finally:
        container.close()


def extract_srt(path: str, pos: int) -> tuple[str | None, str]:
    """提取第 pos 条字幕流为 SRT 文本，返回 (srt, 错误信息空串=成功)。"""
    container = _av_open(path)
    try:
        subs = container.streams.subtitles
        if pos >= len(subs):
            return None, "字幕流不存在"
        stream = subs[pos]
        items: list[tuple[float, float, str]] = []
        for packet in container.demux(stream):
            if packet.pts is None:
                continue
            try:
                ss = stream.codec_context.decode2(packet)
            except Exception:
                continue
            if ss is None:
                continue
            texts = []
            for rect in ss.rects:
                if rect.type not in (b"ass", b"text"):
                    continue
                raw = rect.text or rect.dialogue or rect.ass
                text = (raw or b"").decode("utf-8", "replace").strip()
                if text:
                    texts.append(text)
            if not texts:
                continue
            start = (ss.pts + ss.start_display_time * 1000) / _AV_TIME_BASE
            end = (ss.pts + ss.end_display_time * 1000) / _AV_TIME_BASE
            if end <= start and packet.duration and packet.time_base:
                end = start + packet.duration * float(packet.time_base)
            items.append((start, end, "\n".join(texts)))
        if not items:
            return None, "该字幕流无可提取文本（可能为图形字幕）"
        items.sort(key=lambda x: x[0])
        lines = [
            f"{i}\n{_ts(st)} --> {_ts(en)}\n{txt}"
            for i, (st, en, txt) in enumerate(items, 1)
        ]
        return "\n\n".join(lines) + "\n", ""
    except Exception as e:
        return None, f"提取失败: {e}"
    finally:
        container.close()


def _ts(sec: float) -> str:
    """秒 → SRT 时间戳 HH:MM:SS,mmm。"""
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

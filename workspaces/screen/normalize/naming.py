"""文件名拼装（screen）— 文本槽位 + 媒体技术槽位 → 规范文件名。

与 ai_slots.py（AI 补全文本槽位）、media_probe.py（PyAV 读技术槽位）分工：
这里只做「槽位 → 全名/三级相对路径」，不掺任何提示词/LLM 调用。
"""

import re
from pathlib import Path

from workspaces.screen.normalize.media_probe import probe


def _join(*parts: str) -> str:
    """用 . 拼接非空段（可空槽位自动跳过）。"""
    return ".".join(p for p in parts if p)


def _assemble_movie(key: str, slots: dict, tech: dict) -> str:
    """电影槽位 → 全名；zh/en/year 必填缺失返回空串（交由 _errors）。"""
    zh = (slots.get("zh") or "").strip()
    en = (slots.get("en") or "").strip()
    year = (slots.get("year") or "").strip()
    if not (zh and en and year):
        return ""
    score = (slots.get("score") or "").strip()
    sub = (slots.get("sub") or "").strip() or tech.get("sub", "")
    return _join(
        zh, en, year,
        (slots.get("edition") or "").strip(),
        f"豆{score}" if score else "",
        (slots.get("source") or "").strip(),
        tech.get("dts", ""),
        tech.get("resolution", ""),
        tech.get("codec", ""),
        tech.get("bitdepth", ""),
        tech.get("hdr", ""),
        tech.get("audio_codec", ""),
        tech.get("channels", ""),
        tech.get("audio_tracks", ""),
        sub,
        Path(key).suffix.lstrip("."),
    )


def _assemble_tv(key: str, slots: dict, tech: dict) -> str:
    """电视剧槽位 → 三级相对路径（系列/季/集）；zh/en/season/episode 必填缺失返回空串。"""
    zh = (slots.get("zh") or "").strip()
    en = (slots.get("en") or "").strip()
    season = (slots.get("season") or "").strip()
    episode = (slots.get("episode") or "").strip()
    if not (zh and en and season and episode):
        return ""
    year = (slots.get("year") or "").strip()
    subtitle = (slots.get("subtitle") or "").strip()
    score = (slots.get("score") or "").strip()
    sub = (slots.get("sub") or "").strip() or tech.get("sub", "")
    series = _join(zh, en)
    season_dir = _join(f"S{season}", zh, en, year)
    ep_head = f"{zh}.{en}.S{season}E{episode}" + (f"_{subtitle}" if subtitle else "")
    ep_file = _join(
        ep_head,
        (slots.get("edition") or "").strip(),
        f"豆{score}" if score else "",
        (slots.get("source") or "").strip(),
        tech.get("dts", ""),
        tech.get("resolution", ""),
        tech.get("codec", ""),
        tech.get("bitdepth", ""),
        tech.get("hdr", ""),
        tech.get("audio_codec", ""),
        tech.get("channels", ""),
        tech.get("audio_tracks", ""),
        sub,
        Path(key).suffix.lstrip("."),
    )
    return f"{series}/{season_dir}/{ep_file}"


def assemble(mapping: dict, src_dir, profile: str) -> tuple[dict[str, str], list[str]]:
    """LLM 槽位 dict → (拼装映射, 源文件缺失列表)。

    key 与原输入一致（电影=原文件名、电视=原相对路径），value 为新名/新相对路径，与 _apply 的
    from_dir/old 对齐；技术槽位由 media_probe 读源文件，扩展名取原文件。
    LLM 回传的 key 若与磁盘路径对不上（源文件找不到），跳过并列入 missing——否则会静默产出
    技术槽位全空的稀疏名，应用映射时把文件改坏。
    """
    out: dict[str, str] = {}
    missing: list[str] = []
    for key, slots in mapping.items():
        if not isinstance(slots, dict):
            continue
        src = Path(src_dir) / key
        if not src.exists():
            missing.append(key)
            continue
        tech = probe(src)
        if not tech:
            # 源文件存在但 PyAV 读不到任何流数据——严重错误，不能静默拼出空技术槽位
            raise Exception(f"media_probe 未读到流数据: {src}")
        name = _assemble_tv(key, slots, tech) if profile == "tv" else _assemble_movie(key, slots, tech)
        if name:
            out[key] = name
    return out, missing


def assemble_fix(mapping: dict, profile: str = "movie") -> dict[str, str]:
    """修正映射：LLM 只给要改的 zh/en/year/score，这里对既有规范名做原地替换，其余段保留不动。

    movie 规范名前三段=中文名/英文名/年份；tv 系列文件夹名=中文名/英文名（两段）。
    """
    out: dict[str, str] = {}
    for old, slots in mapping.items():
        if not isinstance(slots, dict):
            continue
        if profile == "tv":
            segs = old.split(".")
            zh = (slots.get("zh") or "").strip() or (segs[0] if segs else "")
            en = (slots.get("en") or "").strip() or (segs[1] if len(segs) > 1 else "")
            out[old] = _join(zh, en)
            continue
        stem, _, ext = old.rpartition(".")
        segs = stem.split(".") if stem else []
        zh = (slots.get("zh") or "").strip() or (segs[0] if segs else "")
        en = (slots.get("en") or "").strip() or (segs[1] if len(segs) > 1 else "")
        year = (slots.get("year") or "").strip() or (segs[2] if len(segs) > 2 else "")
        rest = segs[3:] if len(segs) > 3 else []
        score = (slots.get("score") or "").strip()
        idx = next((i for i, s in enumerate(rest) if re.fullmatch(r"豆\d+(\.\d+)?", s)), None)
        if score:
            ns = f"豆{score}"
            if idx is not None:
                rest[idx] = ns
            else:
                rest.insert(0, ns)
        elif idx is not None:
            rest.pop(idx)
        new = _join(zh, en, year, *rest)
        out[old] = f"{new}.{ext}" if ext else new
    return out

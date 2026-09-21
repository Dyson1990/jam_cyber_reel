"""字幕（screen）— 射手 assrt 搜索中英双字并下载，暂不封装。

约定（todo影视.md 第 12 项）：只做搜索 + 下载；目标=root 中文件名标记「无字幕」的文件；
下载产物统一存本模块 subs/ 子目录，供后续人工核对或封装。
"""

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import av

from core.files import VIDEO_EXTENSIONS

ASSTRT_SEARCH_URL = "https://api.assrt.net/v1/sub/search"
ASSTRT_DETAIL_URL = "https://api.assrt.net/v1/sub/detail"
ASSTRT_DELAY = 13.0  # 射手配额 5 次/分钟，间隔 13s 兜底（搜索+详情各算一次）
SAVE_DIR = Path(__file__).with_name("subs")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_last_ts = 0.0


def _throttle() -> None:
    """按配额节流：保证相邻 HTTP 请求间隔 >= ASSTRT_DELAY。"""
    global _last_ts
    wait = ASSTRT_DELAY - (time.time() - _last_ts)
    if wait > 0:
        time.sleep(wait)
    _last_ts = time.time()


def _http_json(url: str):
    _throttle()
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_bytes(url: str) -> bytes:
    _throttle()
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def is_no_subtitle(path) -> bool:
    """文件名字幕槽是否标记「无字幕」——按命名模板第 7 槽用 . 分片精确匹配。"""
    return "无字幕" in Path(path).stem.split(".")


def search_keyword(path) -> str:
    """从文件名取搜索词：优先首个 . 分片（中文名槽），非中文则退回中文字段。"""
    stem = Path(path).stem
    first = stem.split(".")[0].strip()
    if any("一" <= c <= "鿿" for c in first):
        return first
    m = re.search(r"[一-鿿][一-鿿A-Za-z0-9·：:]*", stem)
    return m.group(0) if m else first


def search_subs(token: str, keyword: str) -> list[dict]:
    """搜索并筛选中英双字，返回 [{id,title,desc,subtype,down_count,upload_time}]。

    双字判定：lang.langlist.langdou 为真（desc 里含「双语」）。
    """
    q = urllib.parse.quote(keyword)
    data = _http_json(f"{ASSTRT_SEARCH_URL}?token={token}&q={q}&cnt=15")
    subs = ((data.get("sub") or {}).get("subs")) or []
    out = []
    for s in subs:
        if not isinstance(s, dict):
            continue
        lang = s.get("lang") or {}
        if not (lang.get("langlist") or {}).get("langdou"):
            continue
        out.append({
            "id": s.get("id"),
            "title": s.get("native_name") or s.get("title") or "",
            "desc": lang.get("desc", ""),
            "subtype": s.get("subtype", ""),
            "down_count": s.get("down_count", 0),
            "upload_time": s.get("upload_time", ""),
        })
    return out


def download_subs(token: str, sub_id, base: str) -> list[str]:
    """下载某字幕的首个文件到 SAVE_DIR，返回保存路径列表（空=无可下载文件）。

    详情返回的 filelist 每项已是独立文件（ass/srt）直链，取第一项即可；
    文件以视频 stem 命名，便于后续按同名匹配封装。
    """
    data = _http_json(f"{ASSTRT_DETAIL_URL}?token={token}&id={sub_id}")
    subs = ((data.get("sub") or {}).get("subs")) or []
    if not subs:
        return []
    fl = subs[0].get("filelist") or []
    if not fl:
        return []
    f = fl[0]
    url = f.get("url")
    if not url:
        return []
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(f.get("f") or "").suffix or ".ass"
    out = SAVE_DIR / f"{base}{ext}"
    out.write_bytes(_http_bytes(url))
    return [str(out)]


# ==================== 封装 ====================

SUB_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt"}
SUB_KINDS = ("中文字幕", "中英双字")


def _is_muxed(stem: str) -> bool:
    """是否本模块的封装产物（文件名带字幕类型槽，含 _N 后缀）。

    封装输出与源视频同目录，再扫时会误当新视频、与对应字幕打平（一个字幕两个视频），
    故扫描时排除带字幕类型槽的文件。
    """
    return any(p.startswith(SUB_KINDS) for p in stem.split("."))


def _read_text(path: Path) -> str:
    """读字幕文件文本：优先 UTF-8，失败回退 GBK/UTF-16（中文外挂字幕常见编码）。"""
    raw = path.read_bytes()
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _sub_lines(text: str) -> str:
    """字幕文本 → 纯台词（去时间轴/序号/ass 样式头，保留对话文本）。"""
    lines = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or re.fullmatch(r"\d+", ln) or "-->" in ln:
            continue
        if ln.startswith(("WEBVTT", "STYLE", "NOTE", "Kind:", "Language:")):
            continue
        if ln.startswith("Dialogue:"):
            # ass 台词在最后一个逗号字段（Format 共 10 段，文本可能含逗号）
            ln = ln.split(",", 9)[-1]
        lines.append(ln)
    return "\n".join(lines)


def subtitle_kind(path: Path) -> str:
    """检测字幕类型：中英双字（台词含英文）/ 中文字幕（仅中文）。

    双字字幕每句台词中英成对，英文台词行数≈中文行数；纯中文字幕里零星英文（OK/人名）
    占比远低于中文行数，故以「英文行 ≥ 中文行一半」判双字，避免误判。
    """
    cn = en = 0
    for ln in _sub_lines(_read_text(path)).splitlines():
        if any("一" <= c <= "鿿" for c in ln):
            cn += 1
        if re.search(r"[A-Za-z]{2,}", ln):
            en += 1
    return "中英双字" if (cn and en >= 2 and en * 2 >= cn) else "中文字幕"


_EP_RE = re.compile(r"^(?:s\d{1,2}e\d{1,2}+|e\d{1,3}|ep\d{1,3})$", re.I)


def _ep_code(stem: str) -> str | None:
    """取剧集码（S03E01 / E01 / EP01），用于跨集防误配；无则 None。"""
    for seg in stem.split("."):
        if _EP_RE.match(seg):
            return seg.upper()
    return None


def _common_segs(a: str, b: str) -> int:
    """两 stem 按 . 分片的公共前缀段数。"""
    n = 0
    for x, y in zip(a.split("."), b.split(".")):
        if x != y:
            break
        n += 1
    return n


def _match_video(videos: list[Path], sub_stem: str) -> Path | None:
    """为字幕找唯一视频：stem 完全一致优先，否则取公共前缀最长且唯一者。

    视频与字幕常只有发布组/编码段不同（如视频 WEBRip 对字幕 WEB-DL），整段前缀
    匹配不到，故按 . 分片取公共前缀兜底；剧集码不一致直接排除，避免正确集缺失时
    跨集误配（S03E01 字幕误配到仅存的 S03E02 视频）。
    """
    for v in videos:
        if v.stem == sub_stem:
            return v
    sub_ep = _ep_code(sub_stem)
    best, cands = -1, []
    for v in videos:
        if sub_ep:
            v_ep = _ep_code(v.stem)
            if v_ep and v_ep != sub_ep:
                continue
        n = _common_segs(v.stem, sub_stem)
        if n < 1:
            continue
        # 单段公共前缀仅当任一方是无点文件名（如「我的剧」）时才可信，
        # 否则「The.Matrix」会误配「The.Matrix.Reloaded」（公共段 The=1）。
        if n == 1 and "." in sub_stem and "." in v.stem:
            continue
        if n > best:
            best, cands = n, [v]
        elif n == best:
            cands.append(v)
    if not cands:
        return None
    return cands[0] if len(cands) == 1 else None


def scan_pairs(path: str) -> dict:
    """扫描目录，按同名匹配视频↔字幕。返回 {pairs:[{video,sub}], orphans_sub:[], orphans_video:[]}。

    匹配优先级：stem 完全一致 → 一方是另一方带「.」的前缀；一个视频只配一条字幕。
    """
    root = Path(path)
    if not root.is_dir():
        return {"pairs": [], "orphans_sub": [], "orphans_video": []}
    videos = sorted(
        f for f in root.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS and not _is_muxed(f.stem)
    )
    subs = sorted(
        f for f in root.iterdir()
        if f.is_file() and f.suffix.lower() in SUB_EXTENSIONS
    )
    pairs: list[dict] = []
    used_v: set[str] = set()
    for s in subs:
        v = _match_video(videos, s.stem)
        if v is not None and str(v) not in used_v:
            pairs.append({"video": v, "sub": s})
            used_v.add(str(v))
    used_sub = {str(p["sub"]) for p in pairs}
    return {
        "pairs": pairs,
        "orphans_sub": [s for s in subs if str(s) not in used_sub],
        "orphans_video": [v for v in videos if str(v) not in used_v],
    }


def _sub_slot(stem: str, kind: str) -> str:
    """文件名加入字幕类型槽：替换既有「无字幕」槽，否则末尾追加。"""
    parts = stem.split(".")
    if "无字幕" in parts:
        return ".".join(kind if p == "无字幕" else p for p in parts)
    return f"{stem}.{kind}"


def mux_subtitle(video: Path, sub: Path, kind: str) -> Path:
    """把字幕作为软字幕轨封装进视频，输出 <stem>.<kind>.mkv。

    视频/音频/既有字幕流直接复制不重编码；字幕与视频走不同 demuxer，故 mkv（缓冲排序）
    比 mp4 更稳，统一输出 mkv。
    """
    out = video.with_name(f"{_sub_slot(video.stem, kind)}.mkv")
    if out.exists():
        stem, c = out.stem, 1
        while out.exists():
            out = out.with_name(f"{stem}_{c}.mkv")
            c += 1
    iv = av.open(str(video), metadata_errors="ignore")
    isub = av.open(str(sub))
    oc = av.open(str(out), "w")
    try:
        vmap = {st: oc.add_stream_from_template(st) for st in iv.streams}
        sst = isub.streams.subtitles[0]
        osst = oc.add_stream_from_template(sst)
        for pkt in iv.demux():
            if pkt.stream in vmap:
                # 流尾会出 size=0 且无 pts/dts 的 flush 包，直接 mux 会 EINVAL
                if pkt.size <= 0:
                    continue
                pkt.stream = vmap[pkt.stream]
                oc.mux(pkt)
        for pkt in isub.demux(sst):
            if pkt.size <= 0:
                continue
            pkt.stream = osst
            oc.mux(pkt)
    finally:
        oc.close()
        iv.close()
        isub.close()
    return out

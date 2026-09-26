"""文件名 → 查询词共享归一化（各数据源共用，不属任一具体源）。"""

import re

# 英文片名检索时的参数噪声词（命中即截断片名）
_TITLE_STOP = frozenset({
    "1080p", "2160p", "720p", "480p", "4k", "bluray", "web-dl", "webdl",
    "bdrip", "x264", "x265", "h264", "h265", "10bit", "remux", "dvdrip",
    "hdrip", "hevc", "avc", "dts", "dts-hd", "truehd", "atmos",
})

# 剧名尾部的季号后缀（第四季 / Season 4），查询前剥离，避免整季被当作独立剧入库
_SEASON_RE = re.compile(r"第\s*([0-9]+|[一二三四五六七八九十]+)\s*季")
_SEASON_EN_RE = re.compile(r"\bseason\s*#?\s*\d+\b", re.IGNORECASE)


def strip_season(title: str) -> str:
    """剥离剧名季号后缀（第四季 / Season 4），返回去空白后的片名。"""
    s = _SEASON_RE.sub(" ", title or "")
    s = _SEASON_EN_RE.sub(" ", s)
    return " ".join(s.split())


def title_query(filename: str) -> str:
    """从原始文件名粗糙提取片名作搜索词（供各数据源检索，非精确）。"""
    name = filename.rsplit(".", 1)[0] if "." in filename else filename
    for cut in "([【":
        name = name.split(cut, 1)[0]
    name = strip_season(name)
    name = name.replace(".", " ").replace("_", " ").strip()
    tokens = name.split()
    if not tokens:
        return ""
    if any("一" <= c <= "鿿" for c in tokens[0]):
        return tokens[0]  # 首个 token 是中文 → 当作片名
    out = []
    for t in tokens:
        if re.fullmatch(r"(19|20)\d{2}", t) or t.lower() in _TITLE_STOP:
            break
        out.append(t)
    return " ".join(out)


def extract_year(filename: str) -> str:
    """从文件名提取 4 位年份（19xx/20xx），无则空串；用于同名多版消歧。"""
    m = re.search(r"(?:19|20)\d{2}", filename)
    return m.group(0) if m else ""

"""豆瓣数据源 — 标题 → subjectId（搜索联想）→ 详情（apizero），纯豆瓣查询，无缓存。"""

import json
import re
import time
import urllib.parse
import urllib.request

DOUBAN_SUGGEST_URL = "https://www.douban.com/j/search_suggest"
DOUBAN_SUBJECT_SUGGEST_URL = "https://movie.douban.com/j/subject_suggest"
APIZERO_MOVIE_URL = "https://v1.apizero.cn/api/douban-movie"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

SEARCH_DELAY = 3.0  # apizero 匿名接口对连发请求会 429，请求间延时规避（电视剧多源连查，降速更稳妥）

# 英文片名检索时的参数噪声词（命中即截断片名）
_TITLE_STOP = frozenset({
    "1080p", "2160p", "720p", "480p", "4k", "bluray", "web-dl", "webdl",
    "bdrip", "x264", "x265", "h264", "h265", "10bit", "remux", "dvdrip",
    "hdrip", "hevc", "avc", "dts", "dts-hd", "truehd", "atmos",
})


def _http_json(url: str, timeout: float = 8.0):
    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Referer": "https://www.douban.com/"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _search_subject_id(query: str, year: str = "") -> tuple[str | None, dict | None]:
    """标题 → (subjectId, 联想原始 JSON)；空结果延时重试。

    year 提供时优先选年份匹配的卡片，避免同名多版（2010 动画 vs 2025 真人）误配。
    """
    url = f"{DOUBAN_SUGGEST_URL}?q={urllib.parse.quote(query)}"
    for attempt in range(3):
        try:
            data = _http_json(url)
        except Exception as e:
            raise RuntimeError(f"豆瓣搜索失败 {query}: {e}") from e
        cards = data.get("cards", []) if isinstance(data, dict) else []
        movie_cards = []
        for card in cards:
            if not isinstance(card, dict) or card.get("type") != "movie":
                continue
            m = re.search(r"/subject/(\d+)", card.get("url") or "")
            if m:
                movie_cards.append((card, m.group(1)))
        if movie_cards:
            if year:
                for card, sid in movie_cards:
                    if str(card.get("year") or "") == year:
                        return sid, data
            return movie_cards[0][1], data
        if attempt < 2:
            time.sleep(SEARCH_DELAY)
    return None, None


def parse_apizero(data: dict) -> dict:
    """从 apizero 详情 dict 提取 {zh, en, score, year}（纯函数，知识库展示复用）。"""
    if not isinstance(data, dict):
        return {}
    info: dict = {}
    name = data.get("name") or ""
    if name:
        # 豆瓣 name 形如「中文名 英文名」，按首个英文字母拆成中/英文名
        m = re.search(r"[A-Za-z]", name)
        zh = name[:m.start()].strip() if m else name.strip()
        en = name[m.start():].strip() if m else ""
        if zh:
            info["zh"] = zh
        if en:
            info["en"] = en
    score = data.get("score") or data.get("rating") or data.get("douban_score")
    try:
        if score:
            info["score"] = f"{float(score):.1f}"  # 只存数字，列头已是「豆瓣评分」
    except (TypeError, ValueError):
        pass
    year = data.get("year") or data.get("date") or data.get("pubdate")
    if year:
        y = str(year)[:4]
        if y.isdigit():
            info["year"] = y
    return info


def _apizero_info(subject_id: str) -> dict:
    """subjectId → {zh, en, score, year, raw}（apizero，匿名免 Key）；raw 为详情原始 JSON 无删减。"""
    resp = _http_json(f"{APIZERO_MOVIE_URL}?id={urllib.parse.quote(subject_id)}")
    data = resp.get("data") if isinstance(resp, dict) and isinstance(resp.get("data"), dict) else resp
    if not isinstance(data, dict):
        return {}
    info = parse_apizero(data)
    info["raw"] = {"apizero": data}
    return info


def title_query(filename: str) -> str:
    """从原始文件名粗糙提取片名作搜索词（供各数据源检索，非精确）。"""
    name = filename.rsplit(".", 1)[0] if "." in filename else filename
    for cut in "([【":
        name = name.split(cut, 1)[0]
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


def fetch_douban(query: str, year: str = "") -> dict | None:
    """纯豆瓣：片名 → {zh, en, score, year, raw}；无缓存，供上层包装知识库。"""
    sid, suggest_raw = _search_subject_id(query, year)
    if not sid:
        return None
    info = _apizero_info(sid)
    if not info:
        return None
    if suggest_raw is not None:
        info["raw"]["suggest"] = suggest_raw
    return info


_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_SEASON_RE = re.compile(r"第\s*([0-9]+|[一二三四五六七八九十]+)\s*季")


def _season_num(title: str) -> int | None:
    """从「第X季」提取季号（阿拉伯/中文数字），无则 None；十一季以上罕见，不解析。"""
    m = _SEASON_RE.search(title or "")
    if not m:
        return None
    t = m.group(1)
    return int(t) if t.isdigit() else _CN_NUM.get(t)


def fetch_douban_tv(query: str, year: str = "") -> dict | None:
    """剧名 → {zh,en,year,seasons,score,finished,raw}：纯豆瓣，不打其它源。

    各季联想列表(subject_suggest)列出一部剧的各季（含集数/年份/英文副标题），由此推：
    季数=最大季号；年份=各季年份去重「、」连接；某季集数 unknow/空→连载，否则完结。
    评分取首季 apizero 详情；中英文名取「标题去季后缀 + 英文副标题」。
    """
    url = f"{DOUBAN_SUBJECT_SUGGEST_URL}?q={urllib.parse.quote(query)}"
    try:
        cards = _http_json(url)
    except Exception as e:
        raise RuntimeError(f"豆瓣剧集搜索失败 {query}: {e}") from e
    if not isinstance(cards, list) or not cards:
        return None
    primary = cards[0]
    sub = (primary.get("sub_title") or "").strip()
    if sub:
        # 同名真人版/剧场版等副标题不同，按首条副标题过滤到本剧各季
        cards = [c for c in cards if (c.get("sub_title") or "").strip().casefold() == sub.casefold()]
    nums = [n for n in (_season_num(c.get("title") or "") for c in cards) if n]
    seasons = str(max(nums)) if nums else ""
    # 一季一年份，按卡片顺序保留重复（多季同年）
    years = [str(c.get("year") or "")[:4] for c in cards if str(c.get("year") or "")[:4].isdigit()]
    finished = "" if any((c.get("episode") or "") in ("", "unknow") for c in cards) else "完结"

    apz = _apizero_info(str(primary.get("id") or "")) if primary.get("id") else {}
    zh = _SEASON_RE.sub("", primary.get("title") or "").strip()
    en = sub if any(ch.isascii() and ch.isalpha() for ch in sub) else ""
    zh = zh or (apz or {}).get("zh", "")
    en = en or (apz or {}).get("en", "")
    if not (zh or en):
        return None
    raw = {"apizero": (apz or {}).get("raw", {}).get("apizero", {}), "suggest": cards}
    return {
        "zh": zh, "en": en,
        "year": "、".join(years) or (apz or {}).get("year", ""),
        "seasons": seasons,
        "score": (apz or {}).get("score", ""),
        "finished": finished,
        "raw": raw,
    }

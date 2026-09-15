"""豆瓣数据源 — 标题 → subjectId（搜索联想）→ 详情（apizero），纯豆瓣查询，无缓存。"""

import json
import logging
import re
import time
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

DOUBAN_SUGGEST_URL = "https://www.douban.com/j/search_suggest"
APIZERO_MOVIE_URL = "https://v1.apizero.cn/api/douban-movie"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

SEARCH_DELAY = 2.0  # apizero 匿名接口对连发请求会 429，请求间延时规避

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


def _search_subject_id(query: str) -> tuple[str | None, dict | None]:
    """标题 → (subjectId, 联想原始 JSON)；空结果延时重试。"""
    url = f"{DOUBAN_SUGGEST_URL}?q={urllib.parse.quote(query)}"
    for attempt in range(3):
        try:
            data = _http_json(url)
        except Exception as e:
            logger.warning("豆瓣搜索失败 %s: %s", query, e)
            return None, None
        cards = data.get("cards", []) if isinstance(data, dict) else []
        for card in cards:
            if not isinstance(card, dict) or card.get("type") != "movie":
                continue
            m = re.search(r"/subject/(\d+)", card.get("url") or "")
            if m:
                return m.group(1), data
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
            info["score"] = f"豆{float(score):.1f}"
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


def fetch_douban(query: str) -> dict | None:
    """纯豆瓣：片名 → {zh, en, score, year, raw}；无缓存，供上层包装知识库。"""
    sid, suggest_raw = _search_subject_id(query)
    if not sid:
        return None
    info = _apizero_info(sid)
    if not info:
        return None
    if suggest_raw is not None:
        info["raw"]["suggest"] = suggest_raw
    return info

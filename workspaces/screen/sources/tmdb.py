"""TMDB 数据源 — 中文名/英文名/年份（免费 API Key，稳定）。

search/movie 用 language=zh-CN 取中文名(title) + 原片名(original_title) + 上映日(release_date)；
中文原片名的片再按 language=en-US 取英文名，避免把中文当英文名。
"""

import json
import logging
import subprocess
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

TMDB_SEARCH_URL = "https://api.themoviedb.org/3/search/movie"
TMDB_MOVIE_URL = "https://api.themoviedb.org/3/movie/{mid}"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


def _http_json(url: str, timeout: float = 8.0):
    """GET JSON；urllib 失败回退 curl。

    TMDB(CloudFront) 会在建立连接后触发 TLS 重协商，Python 的 OpenSSL 3.x 不支持而报
    SSLEOFError；curl 走 Windows Schannel 可正常完成重协商，故作为兜底。
    """
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.debug("urllib 失败，回退 curl: %s", e)
    out = subprocess.run(
        ["curl", "-sS", "--max-time", str(int(timeout)), url],
        capture_output=True, timeout=timeout + 5,
    )
    return json.loads(out.stdout.decode("utf-8"))


def _is_cjk(s: str) -> bool:
    return any("一" <= c <= "鿿" for c in s)


def _movie_detail(mid, api_key: str) -> dict | None:
    """取详情原始 JSON（en-US 取英文名用），失败返回 None。"""
    url = f"{TMDB_MOVIE_URL.format(mid=mid)}?" + urllib.parse.urlencode(
        {"api_key": api_key, "language": "en-US"},
    )
    try:
        data = _http_json(url)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def fetch_tmdb(query: str, api_key: str) -> dict | None:
    """片名 → {zh, en, year, raw}：search/movie 首条，raw 存全量搜索结果（一次拿多少存多少）。"""
    if not api_key:
        return None
    url = f"{TMDB_SEARCH_URL}?" + urllib.parse.urlencode({
        "api_key": api_key, "query": query, "language": "zh-CN",
    })
    try:
        data = _http_json(url)
    except Exception as e:
        raise RuntimeError(f"TMDB 查询失败 {query}: {e}") from e
    results = data.get("results", []) if isinstance(data, dict) else []
    if not results:
        return None
    r = results[0]
    info: dict = {"raw": {"search": data}}
    if r.get("title"):
        info["zh"] = r["title"]
    rd = r.get("release_date") or ""
    if rd and rd[:4].isdigit():
        info["year"] = rd[:4]
    ot = r.get("original_title") or ""
    if ot and not _is_cjk(ot):
        info["en"] = ot
    elif r.get("id"):
        det = _movie_detail(r["id"], api_key)
        if det:
            info["raw"]["movie"] = det
            en = (det.get("title") or "").strip()
            if en and not _is_cjk(en):
                info["en"] = en
    return info or None

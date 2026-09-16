"""Wikidata 数据源 — 中文名/英文名/年份（免 Key，Wikimedia 基础设施，稳定）。

wbsearchentities 按中文名定位条目（过滤 description 含 film/movie），wbgetentities 取中英文
标签与 P577 出版日期年份。
"""

import json
import urllib.parse
import urllib.request

WD_API = "https://www.wikidata.org/w/api.php"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


def _http_json(url: str, timeout: float = 6.0):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _find_qid(query: str) -> tuple[str | None, dict | None]:
    """标题 → (qid, 搜索原始 JSON)；一次取尽量多（limit 20）。"""
    params = urllib.parse.urlencode({
        "action": "wbsearchentities", "search": query, "language": "zh",
        "format": "json", "type": "item", "limit": 20,
    })
    try:
        data = _http_json(f"{WD_API}?{params}")
    except Exception as e:
        raise RuntimeError(f"Wikidata 搜索失败 {query}: {e}") from e
    for item in data.get("search", []):
        desc = (item.get("description") or "").lower()
        if any(k in desc for k in ("film", "movie", "television", "电视")):
            return item.get("id"), data
    return None, data


def fetch_wikidata(query: str) -> dict | None:
    """片名 → {zh, en, year, raw}；raw 存实体 + 搜索原始 JSON 无删减。"""
    qid, search_raw = _find_qid(query)
    if not qid:
        return None
    params = urllib.parse.urlencode({
        "action": "wbgetentities", "ids": qid, "props": "labels|claims",
        "languages": "zh|en", "format": "json",
    })
    try:
        data = _http_json(f"{WD_API}?{params}")
    except Exception as e:
        raise RuntimeError(f"Wikidata 实体获取失败 {query}: {e}") from e
    ent = (data.get("entities") or {}).get(qid, {})
    if not isinstance(ent, dict):
        return None
    info: dict = {"raw": {"entity": ent}}
    if search_raw is not None:
        info["raw"]["search"] = search_raw
    labels = ent.get("labels") or {}
    if labels.get("zh", {}).get("value"):
        info["zh"] = labels["zh"]["value"]
    if labels.get("en", {}).get("value"):
        info["en"] = labels["en"]["value"]
    for claim in (ent.get("claims") or {}).get("P577", []):
        tv = (claim.get("mainsnak") or {}).get("datavalue") or {}
        t = (tv.get("value") or {}).get("time")
        if t and len(t) >= 5 and t[1:5].isdigit():
            info["year"] = t[1:5]
            break
    return info or None

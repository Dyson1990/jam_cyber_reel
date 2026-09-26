"""Wikidata 数据源 — 中文名/英文名/年份/季数（免 Key，Wikimedia 基础设施，稳定）。

wbsearchentities 按中文名定位条目（过滤 description 含 film/movie/television），wbgetentities
取中英文标签、P577 出版日期年份、P2437 季数（电视剧）。
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


def _find_qid(query: str, tv: bool = False) -> tuple[str | None, dict | None]:
    """标题 → (qid, 搜索原始 JSON)；一次取尽量多（limit 20）。

    tv=True 只认电视剧类条目（否则同名电影会污染剧库共识）；电影模式认影视类条目。
    """
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
        if tv:
            if any(k in desc for k in ("television", "电视")):
                return item.get("id"), data
        elif any(k in desc for k in ("film", "movie", "television", "电视")):
            return item.get("id"), data
    return None, data


def _year_of(ent: dict) -> str:
    """取实体首播年：P577（上映）优先，P580（剧集开始）兜底。"""
    for prop in ("P577", "P580"):
        for claim in (ent.get("claims") or {}).get(prop, []):
            dv = (claim.get("mainsnak") or {}).get("datavalue") or {}
            t = (dv.get("value") or {}).get("time")
            if t and len(t) >= 5 and t[1:5].isdigit():
                return t[1:5]
    return ""


def _is_tv_season(ent: dict) -> bool:
    """P31（instance of）含 Q3464665（电视季）才算季条目，排除 P527 里混入的电影/特辑。"""
    for claim in (ent.get("claims") or {}).get("P31", []):
        dv = (claim.get("mainsnak") or {}).get("datavalue") or {}
        if (dv.get("value") or {}).get("id") == "Q3464665":
            return True
    return False


def _season_years(part_ids: list[str]) -> list[str]:
    """跟随 P527「has part」季条目，一次取回全部实体，读每季首播年。"""
    if not part_ids:
        return []
    url = f"{WD_API}?" + urllib.parse.urlencode({
        "action": "wbgetentities", "ids": "|".join(part_ids),
        "props": "claims", "format": "json",
    })
    try:
        data = _http_json(url)
    except Exception:
        return []
    years: list[str] = []
    for pid in part_ids:
        e = (data.get("entities") or {}).get(pid, {})
        if not isinstance(e, dict) or not _is_tv_season(e):
            continue
        y = _year_of(e)
        if y:
            years.append(y)
    return years


def fetch_wikidata(query: str, tv: bool = False) -> dict | None:
    """片名 → {zh, en, year, seasons, raw}；raw 存实体 + 搜索原始 JSON 无删减。"""
    qid, search_raw = _find_qid(query, tv)
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
    # 首播年：电影 P577（上映）、剧集 P580（开始）；剧集再跟 P527 季条目取逐季年份
    first_year = _year_of(ent)
    if tv:
        part_ids: list[str] = []
        for claim in (ent.get("claims") or {}).get("P527", []):
            dv = (claim.get("mainsnak") or {}).get("datavalue") or {}
            pid = (dv.get("value") or {}).get("id")
            if pid:
                part_ids.append(pid)
        years = _season_years(part_ids)
        if years:
            years.sort(key=int)
            info["year"] = "、".join(years)
        elif first_year:
            info["year"] = first_year
    elif first_year:
        info["year"] = first_year
    for claim in (ent.get("claims") or {}).get("P2437", []):
        # P2437「季数」是 quantity，amount 形如 "+3"；去正负号取整数部分（截掉 .0）
        dv = (claim.get("mainsnak") or {}).get("datavalue") or {}
        amt = (dv.get("value") or {}).get("amount")
        if amt:
            num = str(amt).lstrip("+-").split(".")[0]
            if num.isdigit():
                info["seasons"] = num
            break
    return info or None

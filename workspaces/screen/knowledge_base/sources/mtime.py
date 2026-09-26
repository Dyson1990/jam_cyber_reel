"""时光网数据源 — 中文名/英文名/年份（免 Key，官网搜索接口 unionSearch2）。

搜索排序是模糊的（「盗梦空间」会命中一堆「空间」片、把续集排前面），故只认「片名/英文名
精确匹配」的首条，匹配不到返回 None，绝不张冠李戴。
"""

import json
import re
import urllib.parse
import urllib.request

MTIME_SEARCH_URL = "https://front-gateway.mtime.com/mtime-search/search/unionSearch2"

# 时光网把每季当独立「电视剧」条目返回（「黑镜 第二季」），季条目名的尾巴形如「第N季」
_SEASON_TAIL = re.compile(r"第\s*[0-9一二三四五六七八九十]+\s*季")
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _norm(s) -> str:
    return (s or "").strip()


def fetch_mtime(query: str, tv: bool = False) -> dict | None:
    """片名 → {zh, en, year, raw}：仅精确命中才返回，raw 存全量搜索响应。

    tv=True 只认 movieContentType=电视剧 的条目（否则同名电影会混进剧库）；时光网搜索
    无类型过滤参数，只能取回后按内容类型筛。
    """
    body = urllib.parse.urlencode({
        "locationId": "290", "keyword": query, "searchType": "0",
    }).encode("utf-8")
    req = urllib.request.Request(
        MTIME_SEARCH_URL, data=body,
        headers={"User-Agent": _UA, "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"时光网查询失败 {query}: {e}") from e
    movies = (data.get("data") or {}).get("movies") or []
    if tv:
        movies = [m for m in movies if isinstance(m, dict) and m.get("movieContentType") == "电视剧"]
    if not movies:
        return None
    q = _norm(query).casefold()
    hit = None
    for m in movies:
        if not isinstance(m, dict):
            continue
        if _norm(m.get("name")).casefold() == q or _norm(m.get("nameEn")).casefold() == q:
            hit = m
            break
    if hit is None:
        # 兜底：其它中文名（titleOthersCn）精确命中
        for m in movies:
            others = m.get("titleOthersCn") or []
            if isinstance(others, list) and any(_norm(x).casefold() == q for x in others):
                hit = m
                break
    if hit is None:
        return None
    info: dict = {"raw": {"search": data}}
    zh = _norm(hit.get("name"))
    en = _norm(hit.get("nameEn"))
    if zh:
        info["zh"] = zh
    if en and en.casefold() != zh.casefold():
        info["en"] = en
    year = hit.get("year")
    if tv:
        # 主条目=首季；其余同名「第N季」条目各带本季年份，按年份升序拼接成逐季年份
        years = []
        if isinstance(year, int) and 1800 < year < 2100:
            years.append(str(year))
        zlc = zh.casefold()
        if zlc:
            for m in movies:
                if not isinstance(m, dict) or m is hit:
                    continue
                nm = _norm(m.get("name")).casefold()
                if nm.startswith(zlc) and _SEASON_TAIL.fullmatch(nm[len(zlc):].strip()):
                    y = m.get("year")
                    if isinstance(y, int) and 1800 < y < 2100:
                        years.append(str(y))
        years.sort(key=int)
        if years:
            info["year"] = "、".join(years)
    elif isinstance(year, int) and 1800 < year < 2100:
        info["year"] = str(year)
    return info if any(k in info for k in ("zh", "en", "year")) else None

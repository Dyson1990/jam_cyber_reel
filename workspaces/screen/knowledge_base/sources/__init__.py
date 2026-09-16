"""screen 数据源统一入口 — 豆瓣优先，豆瓣缺失时用其它源自纠错，结果固化进知识库。

策略（todo影视.md 第 4 项）：
    1. 优先查知识库（chromadb 固化）；
    2. 豆瓣优先，豆瓣拿到完整 {zh,en,year} 直接采用，缺失则完全弃用；
    3. 豆瓣拿不到 → 取 TMDB（需 Key）/Wikidata，超过半数源三字段完全一致才采用，否则放弃；
    4. 采用结果固化回知识库。
"""

import logging
import time

from ..store import kb_lookup, kb_upsert
from .douban import fetch_douban, title_query, SEARCH_DELAY, extract_year
from .mtime import fetch_mtime
from .tmdb import fetch_tmdb
from .wikidata import fetch_wikidata

logger = logging.getLogger(__name__)

# 熔断：源连续 _MAX_FAILS 次网络/解析异常后本批内跳过，避免被墙的源逐个空等超时。
_MAX_FAILS = 3
_fails: dict[str, int] = {}
_open: set[str] = set()


def reset_breakers() -> None:
    """每个批量任务开始时复位，让本轮重新探测各源可达性。"""
    _fails.clear()
    _open.clear()


def _call(source: str, fn):
    """带熔断地调用数据源。仅异常算失败；源可达但未命中（返回 None）不算。"""
    if source in _open:
        return None
    try:
        out = fn()
    except Exception as e:
        _fails[source] = _fails.get(source, 0) + 1
        if _fails[source] >= _MAX_FAILS:
            _open.add(source)
        logger.warning("%s", e)
        return None
    _fails[source] = 0
    return out


def _consensus(cands: list[dict]) -> dict | None:
    """自纠错：仅当「三字段齐全」的源中，超过半数给出完全一致的三元组时采用，否则 None。

    3 字段/4 源下逐字段投票易被单源噪声带偏，改为整条三元组严格共识：
    en 忽略大小写比对；缺任一字段的源无法「完全一致」，不参与。
    """
    full = [c for c in cands if c.get("zh") and c.get("en") and c.get("year")]
    if not full:
        return None
    groups: dict[tuple, list[dict]] = {}
    for c in full:
        key = (c["zh"].strip(), c["en"].strip().casefold(), c["year"].strip())
        groups.setdefault(key, []).append(c)
    for key, grp in groups.items():
        if len(grp) > len(full) / 2:
            c = grp[0]
            return {"zh": c["zh"], "en": c["en"], "year": c["year"]}
    return None


def _persist(info: dict, query: str, raw: dict | None = None) -> dict:
    kb_upsert(
        info.get("zh", ""), info.get("en", ""), info.get("year", ""),
        info.get("score", ""), query, raw,
    )
    return info


def fetch_info(query: str, tmdb_key: str = "", mode: str = "auto", year: str = "") -> dict | None:
    """片名 → {zh,en,year,score,raw}。

    mode 决定用哪些源：
        "douban" — 仅豆瓣（含评分）
        "all"    — 仅豆瓣之外的其它源（TMDB/Wikidata/时光网）自纠错，不含评分
        "auto"   — 豆瓣优先，缺失时回退其它源（默认，normalize 用）
    """
    cached = kb_lookup(query)
    if cached:
        return cached

    # 各源一手数据无删减收集（无论是否参与最终结果，都固化进知识库）
    raw: dict = {}
    if mode != "all":
        d = _call("douban", lambda: fetch_douban(query, year))
        if d and d.get("raw"):
            raw["douban"] = d["raw"]
        if d and d.get("zh") and d.get("en") and d.get("year"):
            return _persist(d, query, raw)
        if mode == "douban":
            return None

    # 豆瓣之外的源自纠错（mode="all" 直接走这里；"auto" 豆瓣失败后回退到这里）
    cands: list[dict] = []
    if tmdb_key:
        t = _call("tmdb", lambda: fetch_tmdb(query, tmdb_key))
        if t:
            if t.get("raw"):
                raw["tmdb"] = t["raw"]
            cands.append(t)
    w = _call("wikidata", lambda: fetch_wikidata(query))
    if w:
        if w.get("raw"):
            raw["wikidata"] = w["raw"]
        cands.append(w)
    m = _call("mtime", lambda: fetch_mtime(query))
    if m:
        if m.get("raw"):
            raw["mtime"] = m["raw"]
        cands.append(m)

    out = _consensus(cands)
    if not out:
        return None
    return _persist(out, query, raw)


def fetch_infos(names: list[str], tmdb_key: str = "") -> dict[str, dict]:
    """批量取信息 {文件名: {zh,en,year,score}}；请求间延时规避限流，单条失败跳过。"""
    reset_breakers()
    infos: dict[str, dict] = {}
    for n in names:
        q = title_query(n)
        if not q:
            continue
        try:
            info = fetch_info(q, tmdb_key, year=extract_year(n))
        except Exception as e:
            logger.warning("取信息失败 %s: %s", q, e)
        else:
            if info:
                infos[n] = info
        time.sleep(SEARCH_DELAY)
    return infos

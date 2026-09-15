"""screen 数据源统一入口 — 豆瓣优先，豆瓣缺失时用其它源自纠错，结果固化进知识库。

策略（todo影视.md 第 4 项）：
    1. 优先查知识库（chromadb 固化）；
    2. 豆瓣优先，豆瓣拿到完整 {zh,en,year} 直接采用，缺失则完全弃用；
    3. 豆瓣拿不到 → 取 TMDB（需 Key）/Wikidata，超过半数源三字段完全一致才采用，否则放弃；
    4. 采用结果固化回知识库。
"""

import logging
import time

from workspaces.screen.kb import kb_lookup, kb_upsert
from workspaces.screen.sources.douban import fetch_douban, title_query, SEARCH_DELAY
from workspaces.screen.sources.mtime import fetch_mtime
from workspaces.screen.sources.tmdb import fetch_tmdb
from workspaces.screen.sources.wikidata import fetch_wikidata

logger = logging.getLogger(__name__)


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


def fetch_info(query: str, tmdb_key: str = "") -> dict | None:
    """片名 → {zh,en,year,score,raw}；豆瓣优先，缺失则其它源半数一致才固化。"""
    cached = kb_lookup(query)
    if cached:
        return cached

    # 各源一手数据无删减收集（无论是否参与最终结果，都固化进知识库）
    raw: dict = {}
    d = fetch_douban(query)
    if d and d.get("raw"):
        raw["douban"] = d["raw"]
    if d and d.get("zh") and d.get("en") and d.get("year"):
        return _persist(d, query, raw)

    # 豆瓣不完整则结果弃用（其切分不可靠），只靠其它源自纠错
    cands: list[dict] = []
    if tmdb_key:
        t = fetch_tmdb(query, tmdb_key)
        if t:
            if t.get("raw"):
                raw["tmdb"] = t["raw"]
            cands.append(t)
    w = fetch_wikidata(query)
    if w:
        if w.get("raw"):
            raw["wikidata"] = w["raw"]
        cands.append(w)
    m = fetch_mtime(query)
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
    infos: dict[str, dict] = {}
    for n in names:
        q = title_query(n)
        if not q:
            continue
        try:
            info = fetch_info(q, tmdb_key)
        except Exception as e:
            logger.warning("取信息失败 %s: %s", q, e)
        else:
            if info:
                infos[n] = info
        time.sleep(SEARCH_DELAY)
    return infos

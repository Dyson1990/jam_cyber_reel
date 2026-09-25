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
from .douban import fetch_douban, fetch_douban_tv, title_query, SEARCH_DELAY, extract_year
from .mtime import fetch_mtime
from .tmdb import fetch_tmdb, fetch_tmdb_tv, _is_latin
from .tvdb import fetch_tvdb
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


def _consensus_tv(cands: list[dict]) -> dict | None:
    """TV 自纠错：年份逐季多值、跨源难对齐，仅按中英文名共识；取多数一致的完整候选（自带季数/是否完结/年份）。"""
    full = [c for c in cands if c.get("zh") and c.get("en")]
    if not full:
        return None
    groups: dict[tuple, list[dict]] = {}
    for c in full:
        key = (c["zh"].strip(), c["en"].strip().casefold())
        groups.setdefault(key, []).append(c)
    for grp in groups.values():
        if len(grp) > len(full) / 2:
            return grp[0]
    return None


_last_miss: str = ""


def last_miss_reason() -> str:
    """返回最近一次 fetch_info 未命中原因（供 UI 日志展示），命中返回空串。"""
    return _last_miss


def _miss_reason(entries: list[tuple[str, dict | None]]) -> str:
    """未命中原因归纳：无结果 / 缺中英文名 / 名字不一致，附各源返回摘要。"""
    got = [(n, c) for n, c in entries if c]
    if not got:
        return "各源均无结果（不可达/限流，或库中无此剧）"
    parts = []
    for n, c in got:
        zh = (c.get("zh") or "").strip()
        en = (c.get("en") or "").strip()
        parts.append(f"{n}[{'中英' if zh and en else '中文' if zh else '英文' if en else '无'}]")
    return "源有结果但未过共识：" + "/".join(parts)


def _persist(info: dict, query: str, raw: dict | None, profile: str) -> dict:
    zh = (info.get("zh") or "").strip()
    en = (info.get("en") or "").strip()
    if zh and _is_latin(zh):
        # 源返回的「中文名」实为英文（该片无中文译名）→ 归入英文名，中文名留空
        en = en or zh
        zh = ""
        info["zh"], info["en"] = zh, en
    kb_upsert(
        zh, en, info.get("year", ""),
        info.get("score", ""), query, raw, profile=profile,
        seasons=info.get("seasons", ""), finished=info.get("finished", ""),
        episodes=info.get("episodes"), subtitle_status=info.get("subtitle_status", ""),
    )
    return info


def _align_tv_year(out: dict, t_tv: dict | None) -> dict:
    """年份个数与季数对齐：季数>1 时年份按季补齐，保证展示一一对应。

    TMDB 是唯一给出逐季 air_date 的源（TVDB/时光/维基只有首播年）；TMDB 季数与共识
    结果一致时优先用其逐季年份，否则把已知首播年重复补齐（如 3 季同年 → 2022、2022、2022）。
    """
    try:
        n = int(str(out.get("seasons") or ""))
    except (TypeError, ValueError):
        return out
    if n <= 1:
        return out
    src = out.get("year") or ""
    if t_tv:
        try:
            if int(str(t_tv.get("seasons") or "")) == n:
                src = t_tv.get("year") or src
        except (TypeError, ValueError):
            pass
    ys = [y for y in src.split("、") if y.strip()]
    if not ys:
        return out
    if len(ys) < n:
        ys += [ys[-1]] * (n - len(ys))
    out = dict(out)
    out["year"] = "、".join(ys[:n])
    return out


def _fetch_tv(query: str, tmdb_key: str, tvdb_key: str, mode: str, year: str) -> dict | None:
    """剧名 → {zh,en,year,seasons,score,finished,raw}。与电影同构，仅源函数换成电视剧版。

    电视剧逐季逐集更新，季数/是否完结每次重查数据源（不查缓存短路）。
    """
    raw: dict = {}
    if mode != "all":
        d = _call("douban", lambda: fetch_douban_tv(query, year))
        if d and d.get("raw"):
            raw["douban"] = d["raw"]
        if d and d.get("zh") and d.get("en") and d.get("year"):
            return _persist(d, query, raw, "tv")
        if mode == "douban":
            return None

    # 豆瓣之外的源自纠错（季数/是否完结仅 TMDB/TVDB 提供，随共识候选一并返回）
    cands: list[dict] = []
    t_tv = v_tv = None
    if tmdb_key:
        t_tv = _call("tmdb_tv", lambda: fetch_tmdb_tv(query, tmdb_key))
        if t_tv:
            if t_tv.get("raw"):
                raw["tmdb"] = t_tv["raw"]
            cands.append(t_tv)
    if tvdb_key:
        v_tv = _call("tvdb", lambda: fetch_tvdb(query, tvdb_key))
        if v_tv:
            if v_tv.get("raw"):
                raw["tvdb"] = v_tv["raw"]
            cands.append(v_tv)
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

    # TMDB+TVDB 两个专业剧库中英文名一致即强信号直接采用：wikidata/时光网对剧集常返回
    # 错实体或无剧集，会稀释多源共识，把本可 2 票命中的误判成 2/4 未过半。
    out = None
    if t_tv and v_tv:
        tz = (t_tv.get("zh") or "").strip()
        te = (t_tv.get("en") or "").strip().casefold()
        vz = (v_tv.get("zh") or "").strip()
        ve = (v_tv.get("en") or "").strip().casefold()
        if tz and te and tz == vz and te == ve:
            out = t_tv  # 用 TMDB 候选，年份为逐季「、」连接，与既有展示一致
    if not out:
        out = _consensus_tv(cands)
    if not out:
        global _last_miss
        _last_miss = _miss_reason([("TMDB", t_tv), ("TVDB", v_tv), ("维基", w), ("时光", m)])
        return None
    return _persist(_align_tv_year(out, t_tv), query, raw, "tv")


def fetch_info(query: str, tmdb_key: str = "", mode: str = "auto", year: str = "", profile: str = "movie", tvdb_key: str = "") -> dict | None:
    """片名 → {zh,en,year,score,raw}。

    mode 决定用哪些源：
        "douban" — 仅豆瓣（含评分）
        "all"    — 仅豆瓣之外的其它源（TMDB/Wikidata/时光网）自纠错，不含评分
        "auto"   — 豆瓣优先，缺失时回退其它源（默认，normalize 用）
    profile 决定写入/读取哪个 profile 的知识库集合（movie/tv 分开）；tv 逐季更新不查缓存。
    """
    if profile == "tv":
        return _fetch_tv(query, tmdb_key, tvdb_key, mode, year)
    cached = kb_lookup(query, profile=profile)
    if cached:
        return cached

    # 各源一手数据无删减收集（无论是否参与最终结果，都固化进知识库）
    raw: dict = {}
    if mode != "all":
        d = _call("douban", lambda: fetch_douban(query, year))
        if d and d.get("raw"):
            raw["douban"] = d["raw"]
        if d and d.get("zh") and d.get("en") and d.get("year"):
            return _persist(d, query, raw, profile)
        if mode == "douban":
            return None

    # 豆瓣之外的源自纠错（mode="all" 直接走这里；"auto" 豆瓣失败后回退到这里）
    cands: list[dict] = []
    t = None
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
        global _last_miss
        _last_miss = _miss_reason([("TMDB", t), ("维基", w), ("时光", m)])
        return None
    return _persist(out, query, raw, profile)


def fetch_infos(names: list[str], tmdb_key: str = "", profile: str = "movie", tvdb_key: str = "") -> dict[str, dict]:
    """批量取信息 {文件名: {zh,en,year,score}}；请求间延时规避限流，单条失败跳过。"""
    reset_breakers()
    infos: dict[str, dict] = {}
    for n in names:
        q = title_query(n)
        if not q:
            continue
        try:
            info = fetch_info(q, tmdb_key, year=extract_year(n), profile=profile, tvdb_key=tvdb_key)
        except Exception as e:
            logger.warning("取信息失败 %s: %s", q, e)
        else:
            if info:
                infos[n] = info
        time.sleep(SEARCH_DELAY)
    return infos

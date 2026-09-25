"""TMDB 数据源 — 中文名/英文名/年份（免费 API Key，稳定）。

search/movie 用 language=zh-CN 取中文名(title) + 原片名(original_title) + 上映日(release_date)；
中文原片名的片再按 language=en-US 取英文名，避免把中文当英文名。
"""

import json
import logging
import re
import subprocess
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

TMDB_SEARCH_URL = "https://api.themoviedb.org/3/search/movie"
TMDB_MOVIE_URL = "https://api.themoviedb.org/3/movie/{mid}"
TMDB_TV_SEARCH_URL = "https://api.themoviedb.org/3/search/tv"
TMDB_TV_URL = "https://api.themoviedb.org/3/tv/{tid}"
TMDB_TV_SEASON_URL = "https://api.themoviedb.org/3/tv/{tid}/season/{season}"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

# status=Ended/Canceled 表示不再更新（完结）；Returning/In Production 等仍在连载
_FINISHED_STATUS = frozenset({"Ended", "Canceled"})

# 集无独立副标题时的占位名（Episode N / 第 N 集 等），不算副标题
_PLACEHOLDER_RE = re.compile(r"^(?:episode\s*#?\s*\d+|第\s*\d+\s*[集话回]|#\s*\d+)$", re.IGNORECASE)


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


def _is_latin(s: str) -> bool:
    """英文名正向判断：所有字符都在拉丁区（含变音，U+0000–U+024F）。

    超过此区（中日韩/假名/韩文/西里尔/阿拉伯/泰文…）即非英文名。
    用白名单而非黑名单，换任何语言都不会误判。
    """
    return bool(s) and all(c <= "ɏ" for c in s)


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
    # 精确匹配优先：TMDB 常把含搜索词的长名排在精确项前（暗黑者 vs 暗黑），取完全一致者避免错配
    q = query.strip().casefold()
    exact = next((x for x in results
                  if (x.get("title") or "").strip().casefold() == q
                  or (x.get("original_title") or "").strip().casefold() == q), None)
    r = exact or results[0]
    info: dict = {"raw": {"search": data}}
    title = (r.get("title") or "").strip()
    if title and not _is_latin(title):
        info["zh"] = title
    rd = r.get("release_date") or ""
    if rd and rd[:4].isdigit():
        info["year"] = rd[:4]
    ot = r.get("original_title") or ""
    if ot and _is_latin(ot):
        info["en"] = ot
    elif r.get("id"):
        det = _movie_detail(r["id"], api_key)
        if det:
            info["raw"]["movie"] = det
            en = (det.get("title") or "").strip()
            if en and _is_latin(en):
                info["en"] = en
    return info or None


def _tv_episode_subtitles(tid, api_key: str, det: dict) -> tuple[dict[str, str], int]:
    """逐集副标题：对每季取 zh-CN/en-US 两版 season 端点，返回 (副标题映射, 总集数)。

    键=「S{季两位}E{集两位}」与命名槽位对齐；只请求 zh-CN/en-US 两种语言，天然排除其它语言；
    副标题语言按国家定（华语 CN/HK/TW 中文优先、否则英文优先）；占位名（Episode N / 第 N 集）不算副标题，
    用于区分「有/无/部分」。
    """
    if not isinstance(det, dict):
        return {}, 0
    # 华语剧（大陆 CN/香港 HK/台湾 TW）原副标题是中文、英文是译名，中文优先；
    # 其它国家（美/英/日韩等）原副标题是英文，英文优先。origin_country 为 ISO-3166 码数组。
    cn_first = bool({"CN", "HK", "TW"} & set(det.get("origin_country") or []))
    out: dict[str, str] = {}
    total = 0
    for s in det.get("seasons") or []:
        if not isinstance(s, dict) or not s.get("season_number"):
            continue  # 跳过 season 0（特辑/花絮）
        try:
            n = int(s["season_number"])
        except (TypeError, ValueError):
            continue
        zh_eps: dict[int, str] = {}
        en_eps: dict[int, str] = {}
        for lang in ("zh-CN", "en-US"):
            try:
                url = f"{TMDB_TV_SEASON_URL.format(tid=tid, season=n)}?" + urllib.parse.urlencode(
                    {"api_key": api_key, "language": lang},
                )
                data = _http_json(url)
            except Exception:
                data = None
            epmap = {
                int(e["episode_number"]): (e.get("name") or "").strip()
                for e in (data or {}).get("episodes") or []
                if isinstance(e, dict) and e.get("episode_number")
            }
            if lang == "zh-CN":
                zh_eps = epmap
            else:
                en_eps = epmap
        all_nums = sorted(set(zh_eps) | set(en_eps))
        total += len(all_nums)
        for epnum in all_nums:
            zh = zh_eps.get(epnum, "")
            en = en_eps.get(epnum, "")
            # 真实副标题：非占位名；中文须非拉丁，英文须拉丁
            zh_ok = bool(zh) and not _is_latin(zh) and not _PLACEHOLDER_RE.match(zh)
            en_ok = bool(en) and _is_latin(en) and not _PLACEHOLDER_RE.match(en)
            if cn_first:
                sub = zh if zh_ok else (en if en_ok else "")
            else:
                sub = en if en_ok else (zh if zh_ok else "")
            if sub:
                out[f"S{n:02d}E{epnum:02d}"] = sub
    return out, total


def fetch_tmdb_tv(query: str, api_key: str) -> dict | None:
    """剧名 → {zh, en, year, seasons, finished, raw}：search/tv + tv/{id}。

    zh/en 取剧名/original_name；年份取各季 air_date 去重「、」连接（电视剧逐季年份不同）；
    季数取 number_of_seasons；是否完结取 status（Ended/Canceled→完结，连载→空）。
    """
    if not api_key:
        return None
    url = f"{TMDB_TV_SEARCH_URL}?" + urllib.parse.urlencode({
        "api_key": api_key, "query": query, "language": "zh-CN",
    })
    try:
        data = _http_json(url)
    except Exception as e:
        raise RuntimeError(f"TMDB 剧集查询失败 {query}: {e}") from e
    results = data.get("results", []) if isinstance(data, dict) else []
    if not results:
        return None
    # 精确匹配优先：TMDB 常把含搜索词的长名排在精确项前（暗黑者 vs 暗黑），取完全一致者避免错配
    q = query.strip().casefold()
    exact = next((x for x in results
                  if (x.get("name") or "").strip().casefold() == q
                  or (x.get("original_name") or "").strip().casefold() == q), None)
    r = exact or results[0]
    info: dict = {"raw": {"search": data}}
    det = None
    if r.get("id"):
        durl = f"{TMDB_TV_URL.format(tid=r['id'])}?" + urllib.parse.urlencode({
            "api_key": api_key, "language": "zh-CN",
        })
        try:
            det = _http_json(durl)
        except Exception:
            det = None
        if isinstance(det, dict):
            info["raw"]["tv"] = det
    src = det if isinstance(det, dict) else r
    name = (src.get("name") or "").strip()
    if name and not _is_latin(name):
        info["zh"] = name
    ot = src.get("original_name") or ""
    if ot and _is_latin(ot):
        info["en"] = ot
    elif r.get("id"):
        # 原名非拉丁（日漫原名是日文、中文剧原名是中文）→ 回 en-US 取英文名
        durl_en = f"{TMDB_TV_URL.format(tid=r['id'])}?" + urllib.parse.urlencode({
            "api_key": api_key, "language": "en-US",
        })
        try:
            det_en = _http_json(durl_en)
        except Exception:
            det_en = None
        if isinstance(det_en, dict):
            info["raw"]["tv_en"] = det_en
            en = (det_en.get("name") or "").strip()
            if en and _is_latin(en):
                info["en"] = en
    years: list[str] = []
    if isinstance(det, dict):
        for s in det.get("seasons", []) or []:
            if not isinstance(s, dict) or not s.get("season_number"):
                continue  # 跳过 season 0（特辑/花絮）
            ad = str(s.get("air_date") or "")[:4]
            if ad.isdigit():
                years.append(ad)  # 一季一年份，保留重复（多季同年）
        if det.get("number_of_seasons"):
            info["seasons"] = str(det["number_of_seasons"])
        if det.get("status") in _FINISHED_STATUS:
            info["finished"] = "完结"
    if not years:
        fa = str(src.get("first_air_date") or "")[:4]
        if fa.isdigit():
            years.append(fa)
    if years:
        info["year"] = "、".join(years)
    if r.get("id"):
        eps, total = _tv_episode_subtitles(r["id"], api_key, det)
        if eps:
            info["episodes"] = eps
        if total:
            info["subtitle_status"] = (
                "有" if len(eps) == total else "部分" if eps else "无"
            )
    return info or None

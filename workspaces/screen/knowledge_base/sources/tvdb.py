"""TVDB v4 数据源 — 中文名/英文名/年份/季数/是否完结（需 API Key，电视剧专用）。

/v4/login 换 token（有效期 1 个月，模块级缓存）；/v4/search 按剧名搜（translations 含
zho/zhtw/eng 各语言名）；/v4/series/{id}/extended 取官方季序最大季号。
"""

import json
import logging
import subprocess
import time
import urllib.parse
import urllib.request

from .tmdb import _is_latin

logger = logging.getLogger(__name__)

TVDB_API = "https://api4.thetvdb.com/v4"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

# status 与 TMDB 对齐：Ended/Canceled 表示不再更新（完结）
_FINISHED_STATUS = frozenset({"Ended", "Canceled"})

# token 有效期 1 个月，留 5 天余量提前刷新，避免批量中途过期
_TOKEN_TTL = 25 * 24 * 3600
_token = ""
_token_exp = 0.0


def _http_json(url: str, token: str = "", body: dict | None = None, timeout: float = 12.0):
    """GET/POST JSON；urllib 失败回退 curl（Cloudflare TLS 重协商同 TMDB）。"""
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.debug("urllib 失败，回退 curl: %s", e)
    cmd = ["curl", "-sS", "--max-time", str(int(timeout))]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    if body is not None:
        cmd += ["--data-binary", json.dumps(body)]
    cmd.append(url)
    out = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
    return json.loads(out.stdout.decode("utf-8"))


def _login(api_key: str) -> str:
    """换 token；模块级缓存，过期自动重登。"""
    global _token, _token_exp
    now = time.time()
    if _token and now < _token_exp:
        return _token
    data = _http_json(f"{TVDB_API}/login", body={"apikey": api_key})
    _token = (data.get("data") or {}).get("token") or ""
    _token_exp = now + _TOKEN_TTL
    return _token


def fetch_tvdb(query: str, api_key: str) -> dict | None:
    """剧名 → {zh, en, year, seasons, finished, raw}。

    zh 取 translations.zho（简体）/zhtw（繁体），en 取 translations.eng（缺则 name）；
    年份取 first_air_time；季数取官方季序（type=official）最大季号；是否完结取 status。
    """
    if not api_key:
        return None
    token = _login(api_key)
    if not token:
        return None
    url = f"{TVDB_API}/search?" + urllib.parse.urlencode({"query": query, "type": "series"})
    try:
        data = _http_json(url, token=token)
    except Exception as e:
        raise RuntimeError(f"TVDB 剧集查询失败 {query}: {e}") from e
    results = data.get("data", []) if isinstance(data, dict) else []
    if not results:
        return None
    # 精确匹配优先：TVDB 同把含搜索词的长名排在精确项前（暗黑者 vs 暗黑），取 name/translations 完全一致者
    q = query.strip().casefold()
    r = next((x for x in results
              if (x.get("name") or "").strip().casefold() == q
              or any((v or "").strip().casefold() == q
                     for v in (x.get("translations") or {}).values())), results[0])
    info: dict = {"raw": {"search": data}}
    tr = r.get("translations") or {}
    zh = (tr.get("zho") or tr.get("zhtw") or "").strip()
    if zh and not _is_latin(zh):
        info["zh"] = zh
    en = (tr.get("eng") or "").strip()
    if not en or not _is_latin(en):
        nm = (r.get("name") or "").strip()
        if nm and _is_latin(nm):
            en = nm
    if en:
        info["en"] = en
    fa = str(r.get("first_air_time") or r.get("year") or "")[:4]
    if fa.isdigit():
        info["year"] = fa
    if str(r.get("status") or "") in _FINISHED_STATUS:
        info["finished"] = "完结"
    sid = str(r.get("tvdb_id") or "").strip() or str(r.get("id") or "").replace("series-", "").strip()
    if sid:
        eurl = f"{TVDB_API}/series/{sid}/extended"
        try:
            det = _http_json(eurl, token=token)
        except Exception:
            det = None
        if isinstance(det, dict):
            info["raw"]["extended"] = det
            dd = det.get("data") or {}
            nums = [s.get("number") for s in (dd.get("seasons") or [])
                    if isinstance(s, dict) and (s.get("type") or {}).get("type") == "official"
                    and s.get("number")]
            if nums:
                info["seasons"] = str(max(nums))
    return info or None

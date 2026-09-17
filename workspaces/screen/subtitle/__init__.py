"""字幕（screen）— 射手 assrt 搜索中英双字并下载，暂不封装。

约定（todo影视.md 第 12 项）：只做搜索 + 下载；目标=root 中文件名标记「无字幕」的文件；
下载产物统一存本模块 subs/ 子目录，供后续人工核对或封装。
"""

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ASSTRT_SEARCH_URL = "https://api.assrt.net/v1/sub/search"
ASSTRT_DETAIL_URL = "https://api.assrt.net/v1/sub/detail"
ASSTRT_DELAY = 13.0  # 射手配额 5 次/分钟，间隔 13s 兜底（搜索+详情各算一次）
SAVE_DIR = Path(__file__).with_name("subs")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_last_ts = 0.0


def _throttle() -> None:
    """按配额节流：保证相邻 HTTP 请求间隔 >= ASSTRT_DELAY。"""
    global _last_ts
    wait = ASSTRT_DELAY - (time.time() - _last_ts)
    if wait > 0:
        time.sleep(wait)
    _last_ts = time.time()


def _http_json(url: str):
    _throttle()
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_bytes(url: str) -> bytes:
    _throttle()
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def is_no_subtitle(path) -> bool:
    """文件名字幕槽是否标记「无字幕」——按命名模板第 7 槽用 . 分片精确匹配。"""
    return "无字幕" in Path(path).stem.split(".")


def search_keyword(path) -> str:
    """从文件名取搜索词：优先首个 . 分片（中文名槽），非中文则退回中文字段。"""
    stem = Path(path).stem
    first = stem.split(".")[0].strip()
    if any("一" <= c <= "鿿" for c in first):
        return first
    m = re.search(r"[一-鿿][一-鿿A-Za-z0-9·：:]*", stem)
    return m.group(0) if m else first


def search_subs(token: str, keyword: str) -> list[dict]:
    """搜索并筛选中英双字，返回 [{id,title,desc,subtype,down_count,upload_time}]。

    双字判定：lang.langlist.langdou 为真（desc 里含「双语」）。
    """
    q = urllib.parse.quote(keyword)
    data = _http_json(f"{ASSTRT_SEARCH_URL}?token={token}&q={q}&cnt=15")
    subs = ((data.get("sub") or {}).get("subs")) or []
    out = []
    for s in subs:
        if not isinstance(s, dict):
            continue
        lang = s.get("lang") or {}
        if not (lang.get("langlist") or {}).get("langdou"):
            continue
        out.append({
            "id": s.get("id"),
            "title": s.get("native_name") or s.get("title") or "",
            "desc": lang.get("desc", ""),
            "subtype": s.get("subtype", ""),
            "down_count": s.get("down_count", 0),
            "upload_time": s.get("upload_time", ""),
        })
    return out


def download_subs(token: str, sub_id, base: str) -> list[str]:
    """下载某字幕的首个文件到 SAVE_DIR，返回保存路径列表（空=无可下载文件）。

    详情返回的 filelist 每项已是独立文件（ass/srt）直链，取第一项即可；
    文件以视频 stem 命名，便于后续按同名匹配封装。
    """
    data = _http_json(f"{ASSTRT_DETAIL_URL}?token={token}&id={sub_id}")
    subs = ((data.get("sub") or {}).get("subs")) or []
    if not subs:
        return []
    fl = subs[0].get("filelist") or []
    if not fl:
        return []
    f = fl[0]
    url = f.get("url")
    if not url:
        return []
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(f.get("f") or "").suffix or ".ass"
    out = SAVE_DIR / f"{base}{ext}"
    out.write_bytes(_http_bytes(url))
    return [str(out)]

"""screen 知识库 — chromadb 持久化「中文名/英文名/年份/豆瓣评分」映射，优先查库再走豆瓣。

检索只按 metadata 精确过滤（title/中文名/英文名），不依赖向量相似度；向量传固定占位值
以绕过 chromadb 默认 ONNX 嵌入模型首次联网下载。查库未命中则回豆瓣 API 并回写。
"""

import hashlib
import json
import logging
from pathlib import Path

import chromadb

logger = logging.getLogger(__name__)

_KB_DIR = Path(__file__).resolve().parent / "storage"

# chromadb 1.x 要求每条记录必含 documents；我们只按 metadata 精确过滤、从不做向量检索，
# 故显式传入固定向量，避免触发默认 ONNX 嵌入模型首次联网下载。
_EMB = [1.0] * 8

_client = None
_collections: dict[str, object] = {}


def _collection_name(profile: str) -> str:
    """movie 沿用旧集合名 screen_kb 以保留既有数据；其余 profile 各自独立集合。"""
    return "screen_kb" if profile == "movie" else f"screen_kb_{profile}"


def _get_collection(profile: str = "movie"):
    """惰性获取 chromadb collection（按 profile 分集合，进程内复用）。"""
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(_KB_DIR))
    col = _collections.get(profile)
    if col is None:
        col = _client.get_or_create_collection(name=_collection_name(profile))
        _collections[profile] = col
    return col


def _norm(s) -> str:
    return (s or "").strip()


def kb_lookup(query: str, profile: str = "movie") -> dict | None:
    """按片名查库：命中 title/中文名/英文名 任一即返回 {zh,en,year,score}。"""
    q = _norm(query)
    if not q:
        return None
    try:
        res = _get_collection(profile).get(
            where={"$or": [{"title": q}, {"zh": q}, {"en": q}]},
        )
    except Exception:
        logger.warning("知识库查询失败 %s", q, exc_info=True)
        return None
    if res and res["ids"]:
        m = res["metadatas"][0]
        out = {k: m[k] for k in ("zh", "en", "year", "score", "seasons", "finished") if m.get(k)}
        if m.get("raw"):
            try:
                out["raw"] = json.loads(m["raw"])
            except (TypeError, ValueError):
                pass
        return out
    return None


def kb_upsert(zh: str, en: str, year: str, score: str, title: str, raw: dict | None = None, profile: str = "movie", seasons: str = "", finished: str = "") -> None:
    """写入一条映射；raw 为各源一手数据全量（无删减 JSON），以 中文名>英文名>title 派生稳定 id 幂等覆盖。"""
    meta = {}
    for k, v in (("zh", zh), ("en", en), ("year", year), ("score", score), ("title", title), ("seasons", seasons), ("finished", finished)):
        v = _norm(v)
        if v:
            meta[k] = v
    if raw:
        try:
            meta["raw"] = json.dumps(raw, ensure_ascii=False)
        except (TypeError, ValueError):
            pass
    if not meta:
        return
    key = meta.get("zh") or meta.get("en") or meta.get("title") or ""
    cid = hashlib.md5(key.encode("utf-8")).hexdigest()
    try:
        _get_collection(profile).upsert(
            ids=[cid], documents=[key], embeddings=[_EMB], metadatas=[meta],
        )
    except Exception:
        logger.warning("知识库写入失败 %s", key, exc_info=True)


def kb_list(profile: str = "movie") -> list[dict]:
    """返回知识库全部条目 [{zh,en,year,score,title,raw}]，供表格展示。"""
    try:
        res = _get_collection(profile).get()
    except Exception:
        logger.warning("知识库列表读取失败", exc_info=True)
        return []
    out: list[dict] = []
    if not res or not res.get("ids"):
        return out
    for i, mid in enumerate(res["ids"]):
        m = res["metadatas"][i]
        row = {k: m.get(k, "") for k in ("zh", "en", "year", "score", "seasons", "finished", "title")}
        row["_id"] = mid  # 编辑时按稳定 id 定位，避免改中文名导致 id 漂移
        if m.get("raw"):
            try:
                row["raw"] = json.loads(m["raw"])
            except (TypeError, ValueError):
                pass
        out.append(row)
    return out


def kb_delete(cid: str, profile: str = "movie") -> None:
    """按 chromadb id 删除一条（编辑改中文名/英文名会换 id，须先删旧再写新）。"""
    if not cid:
        return
    try:
        _get_collection(profile).delete(ids=[cid])
    except Exception:
        logger.warning("知识库删除失败 %s", cid, exc_info=True)

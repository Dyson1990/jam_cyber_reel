"""screen AI 命名后端 — 基于 LangChain 的 RAG 流程。

思路：
    1. 知识库：标准化规则手写为若干条「自包含、原子化」的 RAG 分块（RULES）。
    2. 索引：各分块经本地哈希嵌入 → 内存向量库（惰性构建）。
    3. 检索：以待标准化文件名作 query，按相似度召回相关规则块并还原顺序。
    4. 生成：ChatDeepSeek 以「召回规则 + 文件名 + 输出约束」生成映射。
"""

import hashlib
import json
import logging
import math
import re
import time
import urllib.parse
import urllib.request

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_deepseek import ChatDeepSeek

DEEPSEEK_MODEL = "deepseek-chat"
EMBED_DIM = 256

# 豆瓣评分数据源：标题→id 用豆瓣搜索建议，id→评分用 apizero（匿名免 Key）
DOUBAN_SUGGEST_URL = "https://movie.douban.com/j/subject_suggest"
APIZERO_MOVIE_URL = "https://v1.apizero.cn/api/douban-movie"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

logger = logging.getLogger(__name__)

# 英文片名检索时的参数噪声词（命中即截断片名）
_TITLE_STOP = frozenset({
    "1080p", "2160p", "720p", "480p", "4k", "bluray", "web-dl", "webdl",
    "bdrip", "x264", "x265", "h264", "h265", "10bit", "remux", "dvdrip",
    "hdrip", "hevc", "avc", "dts", "dts-hd", "truehd", "atmos",
})

_SEARCH_DELAY = 2.0  # apizero 匿名接口对连发请求会 429，请求间延时规避

# 规则知识库：每条自包含，便于单独检索与灵活增删（总结自旧版AI总结.md）
# 规则知识库：一条「标准格式」模板固定槽位顺序，其余规则只描述各槽位的
# 来源（原文件名/查询补充）与可空性，避免「紧接某某之后」这类依赖他字段是否存在的描述。
RULES: list[dict[str, str]] = [
    {
        "topic": "总原则",
        "content": "只使用原文件名已有字段或「## 查询结果」给出的字段；两者都没有则跳过该槽位，"
        "绝不臆造年份、评分、片名等任何信息。",
    },
    {
        "topic": "标准格式",
        "content": "输出文件名按固定槽位模板排列，缺值槽位直接跳过："
        "[中文名].[英文名].[年份].[版本信息].[豆瓣评分].[视频参数].[字幕信息].[扩展名]。",
    },
    {
        "topic": "中文名",
        "content": "来源=原文件名或查询补充，可空。原文件名有中文名则提取；没有时若「## 查询结果」给出则采用；"
        "都没有则跳过。副标题保持原样，不改标点。",
    },
    {
        "topic": "英文名",
        "content": "来源=原文件名或查询补充，可空。原文件名有英文名则提取；没有时若「## 查询结果」给出则采用；"
        "都没有则跳过。空格改下划线 _，英文冒号 : 改中文冒号 ：。",
    },
    {
        "topic": "年份",
        "content": "来源=原文件名或查询补充，可空，格式 .YYYY。原文件名有年份则用原年份；"
        "没有时，若「## 查询结果」给出该片年份则采用；都没有则跳过。",
    },
    {
        "topic": "版本信息",
        "content": "来源=原文件名，可空。保留加长版、完整版、EXTENDED、导演剪辑版、导演剪切版、Director's Cut、"
        "IMAX版、剧场版、重映版、特别版、v2、Unrated、REMASTERED 等；中英等价只保留中文。",
    },
    {
        "topic": "豆瓣评分",
        "content": "来源=查询补充，可空，格式 豆{一位小数}（如 豆8.8）。「## 查询结果」给出评分才写，没给则跳过。",
    },
    {
        "topic": "视频参数",
        "content": "来源=原文件名，可空。只保留已有参数：分辨率 1080p/2160p/720p/1920x800p；编码 x264/x265/H264/H265；"
        "片源 BluRay/WEB-DL/BD/BDrip/ATVP；位深 10bit；杜比视界 DV；无法分离的音频编码（.AAC.2AUDIO.CHS.ENG）。"
        "粘合参数用 . 拆开并统一小写（BD1080P → BD.1080p）。",
    },
    {
        "topic": "删除参数",
        "content": "删除发布组（BATWEB、CTRLHD、CMCT、SONYHD 等）与质量标记（HQ、HDMA、DDP5.1 等）。",
    },
    {
        "topic": "字幕",
        "content": "来源=原文件名。中英字幕/中英双字/CHS-ENG → .中英字幕；特效中英字幕 → .特效中英字幕；"
        "修正特效中英字幕 → .修正特效中英字幕；没有任何字幕标记则写 .无字幕。",
    },
    {
        "topic": "清理",
        "content": "删除广告、网址、发布组等无关信息（如 梦幻天堂·龙网(www.321n.net)、[66影视www.66Ys.Co]、-BATWEB）。",
    },
    {
        "topic": "示例",
        "content": "返老还童.1080p.国英双语.BD中英双字[66影视www.66Ys.Co].mp4 → 返老还童.1080p.BD.中英字幕.mp4；"
        "The.Pursuit.of.Happyness.2006.BluRay.1080p.LPCM5.1.x265.10bit-DreamHD.mkv → "
        "The_Pursuit_of_Happyness.2006.BluRay.1080p.x265.10bit.无字幕.mkv；"
        "海上钢琴师(蓝光国英双音轨170分钟加长版).The.Legend.of.1900.Extended.Cut.1998.BD-1080p.X264.AAC.2AUDIO.CHS.ENG-UUMp4.mp4 → "
        "海上钢琴师.The_Legend_of_1900.1998.加长版.BD-1080p.X264.AAC.2AUDIO.CHS.ENG.mp4；"
        "利刃出鞘2.1080p.BD中英双字[66影视www.66Ys.Co].mp4（查询给英文名 Glass Onion、年份2022、评分豆6.6）→ "
        "利刃出鞘2.Glass_Onion.2022.豆6.6.1080p.BD.中英字幕.mp4。",
    },
]

_JSON_INSTRUCTION = (
    "\n\n## 输出要求\n"
    "仅输出一个 JSON 字典，key 为原文件名，value 为标准化后的文件名，"
    "不要输出任何其他文字或解释。"
)


class HashEmbedding(Embeddings):
    """本地确定性哈希嵌入：字符二元组散列到固定维度向量，离线、零 API 消耗。"""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * EMBED_DIM
        t = text.lower()
        grams = [t[i:i + 2] for i in range(len(t) - 1)] or [t]
        for g in grams:
            h = int(hashlib.md5(g.encode("utf-8")).hexdigest()[:8], 16)
            vec[h % EMBED_DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


_store: InMemoryVectorStore | None = None


def _get_store() -> InMemoryVectorStore:
    """惰性构建规则向量库（首次调用时对各分块嵌入）。"""
    global _store
    if _store is None:
        docs = [
            Document(
                page_content=f"{r['topic']}：{r['content']}",
                metadata={"topic": r["topic"], "idx": i},
            )
            for i, r in enumerate(RULES)
        ]
        _store = InMemoryVectorStore.from_documents(docs, HashEmbedding())
    return _store


def _retrieve(query: str, k: int = 20) -> list[Document]:
    """按相似度召回相关规则块，并按原文顺序还原。"""
    hits = _get_store().similarity_search(query, k=k)
    hits.sort(key=lambda d: d.metadata.get("idx", 0))
    return hits


def build_prompt(
    filenames: list[str], limit: int | None = None, infos: dict[str, dict] | None = None,
) -> str:
    """检索相关规则 + 待标准化文件名（截断到 limit）+ 可选豆瓣信息（评分/年份）→ 组装提示词。"""
    names = filenames[:limit] if limit else filenames
    context = "\n".join(f"- {d.page_content}" for d in _retrieve("\n".join(names)))
    lines = "\n".join(f"{i}. {n}" for i, n in enumerate(names, 1))
    sections = ""
    if infos:
        rows = []
        for i, n in enumerate(names, 1):
            info = infos.get(n)
            if not info:
                continue
            parts = []
            if info.get("zh"):
                parts.append(f"中文名={info['zh']}")
            if info.get("en"):
                parts.append(f"英文名={info['en']}")
            if info.get("year"):
                parts.append(f"年份={info['year']}")
            if info.get("score"):
                parts.append(f"评分={info['score']}")
            if parts:
                rows.append(f"- 第{i}条：{'，'.join(parts)}")
        if rows:
            sections = "\n\n## 查询结果（条目号对应上方文件名序号）\n" + "\n".join(rows)
    return (
        "你是电影文件名标准化助手，请严格依据下列规则处理。\n\n"
        f"## 规则\n{context}\n\n"
        f"## 待标准化文件名\n{lines}{sections}{_JSON_INSTRUCTION}"
    )


def call_deepseek(api_key: str, prompt: str) -> dict[str, str]:
    """以 ChatDeepSeek 生成映射，返回 {原文件名: 新文件名}。"""
    llm = ChatDeepSeek(model=DEEPSEEK_MODEL, api_key=api_key, temperature=0)
    content = llm.invoke(prompt).content
    return _parse_result(content)


def _parse_result(content: str) -> dict[str, str]:
    """从返回文本提取 JSON 字典（容忍 ```json 代码块包裹）。"""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"返回内容不是 JSON 字典: {content[:200]}")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("返回内容不是字典")
    return {str(k): str(v) for k, v in data.items()}


# ==================== 豆瓣评分 ====================

def _http_json(url: str, timeout: float = 8.0):
    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Referer": "https://movie.douban.com/"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _search_subject_id(query: str) -> str | None:
    """标题 → 豆瓣 subjectId（取搜索建议首条）；空结果延时重试以规避限流。"""
    url = f"{DOUBAN_SUGGEST_URL}?q={urllib.parse.quote(query)}"
    for attempt in range(3):
        try:
            data = _http_json(url)
        except Exception as e:
            logger.warning("豆瓣搜索失败 %s: %s", query, e)
            return None
        items = data if isinstance(data, list) else data.get("items", [])
        for it in items:
            if isinstance(it, dict) and it.get("id"):
                return str(it["id"])
        if attempt < 2:
            time.sleep(_SEARCH_DELAY)
    return None


def _apizero_info(subject_id: str) -> dict:
    """subjectId → {zh, en, score, year}（apizero，匿名免 Key）。"""
    data = _http_json(f"{APIZERO_MOVIE_URL}?id={urllib.parse.quote(subject_id)}")
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict):
        return {}
    info: dict = {}
    name = data.get("name") or ""
    if name:
        # 豆瓣 name 形如「中文名 英文名」，按首个英文字母拆成中/英文名
        m = re.search(r"[A-Za-z]", name)
        zh = name[:m.start()].strip() if m else name.strip()
        en = name[m.start():].strip() if m else ""
        if zh:
            info["zh"] = zh
        if en:
            info["en"] = en
    score = data.get("score") or data.get("rating") or data.get("douban_score")
    try:
        if score:
            info["score"] = f"豆{float(score):.1f}"
    except (TypeError, ValueError):
        pass
    year = data.get("year") or data.get("date") or data.get("pubdate")
    if year:
        y = str(year)[:4]
        if y.isdigit():
            info["year"] = y
    return info


def _title_query(filename: str) -> str:
    """从原始文件名粗糙提取片名作搜索词（供豆瓣检索，非精确）。"""
    name = filename.rsplit(".", 1)[0] if "." in filename else filename
    for cut in "([【":
        name = name.split(cut, 1)[0]
    name = name.replace(".", " ").replace("_", " ").strip()
    tokens = name.split()
    if not tokens:
        return ""
    if any("一" <= c <= "鿿" for c in tokens[0]):
        return tokens[0]  # 首个 token 是中文 → 当作片名
    out = []
    for t in tokens:
        if re.fullmatch(r"(19|20)\d{2}", t) or t.lower() in _TITLE_STOP:
            break
        out.append(t)
    return " ".join(out)


def fetch_douban_info(query: str) -> dict | None:
    """按电影名取豆瓣信息 {score, year}；失败返回 None。"""
    sid = _search_subject_id(query)
    if not sid:
        return None
    info = _apizero_info(sid)
    return info or None


def fetch_infos(names: list[str]) -> dict[str, dict]:
    """批量取豆瓣信息 {文件名: {score, year}}；请求间延时规避限流，单条失败跳过。"""
    infos: dict[str, dict] = {}
    for n in names:
        q = _title_query(n)
        if not q:
            continue
        try:
            info = fetch_douban_info(q)
        except Exception as e:
            logger.warning("豆瓣取信息失败 %s: %s", q, e)
        else:
            if info:
                infos[n] = info
        time.sleep(_SEARCH_DELAY)
    return infos

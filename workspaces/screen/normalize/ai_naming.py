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

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_deepseek import ChatDeepSeek

DEEPSEEK_MODEL = "deepseek-v4-flash"
EMBED_DIM = 256

logger = logging.getLogger(__name__)

# 规则知识库：每条自包含，便于单独检索与灵活增删（总结自旧版AI总结.md）
# 规则知识库：一条「标准格式」模板固定槽位顺序，其余规则只描述各槽位的
# 来源（原文件名/查询补充）与可空性，避免「紧接某某之后」这类依赖他字段是否存在的描述。

# 槽位规则（中文名/英文名/年份/版本信息/豆瓣评分/视频参数/字幕/清理）电影与电视剧共享；
# 仅「总原则/标准格式/示例」因电影=单文件、电视剧=文件夹三级结构而分开，提示词因此也分开。
_SLOT_RULES: list[dict[str, str]] = [
    {
        "topic": "中文名",
        "content": "来源=原文件名或查询补充，必填。原文件名有中文名则提取；没有时取「## 查询结果」给出的中文名；"
        "两者都没有则该文件跳过并报错。副标题保持原样，不改标点。",
    },
    {
        "topic": "英文名",
        "content": "来源=原文件名或查询补充，必填。原文件名有英文名则提取；没有时取「## 查询结果」给出的英文名；"
        "两者都没有则该文件跳过并报错。空格改下划线 _；英文冒号（连其后空格）合并成一个中文冒号 ：；"
        "连字符/破折号（- – —）连两侧空格合并成一个连字符 -，均不残留多余下划线"
        "（Mission: Impossible - The Final Reckoning → Mission：Impossible-The_Final_Reckoning）。",
    },
    {
        "topic": "年份",
        "content": "来源=原文件名或查询补充，必填，格式 .YYYY。原文件名有年份则用原年份；"
        "没有时取「## 查询结果」给出的年份；两者都没有则该文件跳过并报错。",
    },
    {
        "topic": "版本信息",
        "content": "来源=原文件名，可空。统一译为中文「XXX版」，同义词归一化（左→右）："
        "EXTENDED/Extended.Cut/加长版→加长版；Director's.Cut/导演剪切版/导演剪辑版→导演剪辑版；"
        "完整版→完整版；IMAX→IMAX版；剧场版→剧场版；重映版→重映版；特别版→特别版；"
        "Unrated→未分级版；REMASTERED→重制版；v2→修正版；映射表之外一律删除。"
        "多个版本信息并存时用顿号、分隔（如 加长版、重制版），不用点号。",
    },
    {
        "topic": "豆瓣评分",
        "content": "来源=查询补充，可空，格式 「豆{一位小数}」（如「豆8.5」）。「## 查询结果」给出评分才写，没给则跳过。",
    },
    {
        "topic": "视频参数",
        "content": "来源=原文件名，可空。只保留已有参数：分辨率 1080p/2160p/720p/1920x800p；编码 x264/x265/H264/H265；"
        "片源 BluRay/WEB-DL/BD/BDrip/ATVP；位深 10bit；杜比视界 DV；音频编码 .AAC.2AUDIO（2AUDIO=双音轨）。"
        "粘合参数用 . 拆开并统一小写（BD1080P → BD.1080p）。字幕语种（CHS/ENG 等）不算视频参数。",
    },
    {
        "topic": "删除参数",
        "content": "删除发布组（BATWEB、CTRLHD、CMCT、SONYHD 等）与质量标记（HQ、HDMA、DDP5.1 等）。",
    },
    {
        "topic": "字幕",
        "content": "来源=原文件名，必填。CHS=中文、ENG=英文；中英字幕/中英双字/CHS.ENG/CHS-ENG → .中英字幕；"
        "特效中英字幕 → .特效中英字幕；修正特效中英字幕 → .修正特效中英字幕；没有任何字幕标记则写 .无字幕。",
    },
    {
        "topic": "清理",
        "content": "删除广告、网址、发布组等无关信息（如 梦幻天堂·龙网(www.321n.net)、[66影视www.66Ys.Co]、-BATWEB）。",
    },
]

# ==================== 电影规则 ====================

RULES: list[dict[str, str]] = [
    {
        "topic": "总原则",
        "content": "只使用原文件名已有字段或「## 查询结果」给出的字段，绝不臆造年份、评分、片名等任何信息。"
        "「中文名/英文名/年份/字幕」四槽位必填：文件名与查询结果都取不到时，该文件不写入映射，"
        "改为在 _errors 中报告错误；其余槽位缺值则直接跳过。",
    },
    {
        "topic": "标准格式",
        "content": "输出文件名按固定槽位模板排列："
        "[中文名].[英文名].[年份].[版本信息].[豆瓣评分].[视频参数].[字幕信息].[扩展名]。"
        "中文名/英文名/年份/字幕必填，版本信息/豆瓣评分/视频参数缺值跳过。",
    },
    *_SLOT_RULES,
    {
        "topic": "示例",
        "content": "爱乐之城.2017.BD1080p.国英双语.中英双字.mp4（查询给英文名 La La Land）→ "
        "爱乐之城.La_La_Land.2017.BD.1080p.中英字幕.mp4；"
        "The.Pursuit.of.Happyness.2006.BluRay.1080p.LPCM5.1.x265.10bit-DreamHD.mkv（查询给中文名 当幸福来敲门）→ "
        "当幸福来敲门.The_Pursuit_of_Happyness.2006.BluRay.1080p.x265.10bit.无字幕.mkv；"
        "海上钢琴师(蓝光国英双音轨170分钟加长版).The.Legend.of.1900.Extended.Cut.1998.BD-1080p.X264.AAC.2AUDIO.CHS.ENG-UUMp4.mp4 → "
        "海上钢琴师.The_Legend_of_1900.1998.加长版.BD-1080p.X264.AAC.2AUDIO.中英字幕.mp4；"
        "利刃出鞘2.1080p.BD中英双字[66影视www.66Ys.Co].mp4（查询给英文名 Glass Onion、年份2022、评分「豆6.6」）→ "
        "利刃出鞘2.Glass_Onion.2022.「豆6.6」.1080p.BD.中英字幕.mp4；"
        "xxx.1080p.mkv（文件名与查询都给不出中文名/英文名/年份）→ 不写入映射，报错：缺中文名/英文名/年份。",
    },
]

# ==================== 电视剧规则 ====================

TV_RULES: list[dict[str, str]] = [
    {
        "topic": "总原则",
        "content": "只使用原文件夹名已有字段或「## 查询结果」给出的字段，绝不臆造年份、评分、片名等任何信息。"
        "电视剧以文件夹为单元：标准化的对象是「系列文件夹名」（from/to/root 顶层的一部剧一个文件夹）。"
        "「中文名/英文名」两槽位必填：文件夹名与查询结果都取不到时，该文件夹不写入映射，"
        "改为在 _errors 中报告错误。",
    },
    {
        "topic": "标准格式",
        "content": "电视剧目录三级结构："
        "系列文件夹=[中文名].[英文名]；"
        "季子文件夹=[中文名].[英文名].[第X季].[年份]；"
        "集文件=[中文名].[英文名].[第X季第Y集].[版本信息].[豆瓣评分].[视频参数].[字幕信息].[扩展名]（与电影模板一致）。"
        "本步骤只输出「系列文件夹名 → 新系列文件夹名」映射，中文名/英文名必填。",
    },
    *_SLOT_RULES,
    {
        "topic": "示例",
        "content": "权力的游戏.Game.of.Thrones（查询给英文名 Game of Thrones）→ 权力的游戏.Game_of_Thrones；"
        "老友记.Friends → 老友记.Friends；"
        "越狱.Prison.Break.2005 → 越狱.Prison_Break；"
        "xxx（文件夹名与查询都给不出中文名/英文名）→ 不写入映射，报错：缺中文名/英文名。",
    },
]

_JSON_INSTRUCTION = (
    "\n\n## 输出要求\n"
    "仅输出一个 JSON 字典：key 为原文件名，value 为标准化后的文件名；"
    "必填槽位取不到、无法标准化的文件不要作为 key 写入映射，"
    "改放入 \"_errors\" 键，值为数组，每项 {\"file\": 原文件名, \"reason\": 缺失说明}；"
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


_RULE_SETS = {"movie": RULES, "tv": TV_RULES}
_stores: dict[str, InMemoryVectorStore] = {}


def _get_store(kind: str) -> InMemoryVectorStore:
    """惰性构建规则向量库（movie/tv 各一份，首次调用时对各分块嵌入）。"""
    if kind not in _stores:
        docs = [
            Document(
                page_content=f"{r['topic']}：{r['content']}",
                metadata={"topic": r["topic"], "idx": i},
            )
            for i, r in enumerate(_RULE_SETS[kind])
        ]
        _stores[kind] = InMemoryVectorStore.from_documents(docs, HashEmbedding())
    return _stores[kind]


def _retrieve(query: str, k: int = 20, kind: str = "movie") -> list[Document]:
    """按相似度召回相关规则块，并按原文顺序还原。"""
    hits = _get_store(kind).similarity_search(query, k=k)
    hits.sort(key=lambda d: d.metadata.get("idx", 0))
    return hits


def _info_section(names: list[str], infos: dict[str, dict] | None) -> str:
    """组装「## 查询结果」段落：条目号 + 中文名/英文名/年份/评分。"""
    if not infos:
        return ""
    rows = []
    for i, n in enumerate(names, 1):
        info = infos.get(n)
        if not info:
            continue
        parts = [
            f"{label}={info[key]}"
            for key, label in (("zh", "中文名"), ("en", "英文名"), ("year", "年份"), ("score", "评分"))
            if info.get(key)
        ]
        if parts:
            rows.append(f"- 第{i}条：{'，'.join(parts)}")
    if not rows:
        return ""
    return "\n\n## 查询结果（条目号对应上方文件名序号）\n" + "\n".join(rows)


def build_prompt(
    filenames: list[str], limit: int | None = None, infos: dict[str, dict] | None = None,
    is_tv: bool = False,
) -> str:
    """检索相关规则 + 待标准化文件名（截断到 limit）+ 可选豆瓣信息（评分/年份）→ 组装提示词。

    is_tv=True 用电视剧规则（文件夹三级结构），提示词与电影分开。
    """
    kind = "tv" if is_tv else "movie"
    names = filenames[:limit] if limit else filenames
    context = "\n".join(f"- {d.page_content}" for d in _retrieve("\n".join(names), kind=kind))
    lines = "\n".join(f"{i}. {n}" for i, n in enumerate(names, 1))
    unit = "文件夹" if is_tv else "文件名"
    role = "电视剧" if is_tv else "电影"
    return (
        f"你是{role}{unit}标准化助手，请严格依据下列规则处理。\n\n"
        f"## 规则\n{context}\n\n"
        f"## 待标准化{unit}\n{lines}{_info_section(names, infos)}{_JSON_INSTRUCTION}"
    )


def build_fix_prompt(
    filenames: list[str], infos: dict[str, dict] | None = None, is_tv: bool = False,
) -> str:
    """AI 修正提示词：仅检查/修正可查询补充槽位（中文名/英文名/年份/豆瓣评分），其余槽位不动。"""
    kind = "tv" if is_tv else "movie"
    names = list(filenames)
    context = "\n".join(f"- {d.page_content}" for d in _retrieve("\n".join(names), kind=kind))
    lines = "\n".join(f"{i}. {n}" for i, n in enumerate(names, 1))
    unit = "文件夹" if is_tv else "文件名"
    role = "电视剧" if is_tv else "电影"
    return (
        f"你是{role}{unit}修正助手。以下{unit}已完成标准化，请仅检查并修正"
        "「中文名 / 英文名 / 年份 / 豆瓣评分」四个可查询补充槽位：依据「## 查询结果」改正错误、"
        f"补上漏查（查询结果有而{unit}缺的字段）；其余槽位（版本信息、视频参数、字幕信息等）一字不改；"
        f"无需修正的{unit}保持原名。\n\n"
        f"## 槽位规范\n{context}\n\n"
        f"## 待检查{unit}\n{lines}{_info_section(names, infos)}{_JSON_INSTRUCTION}"
    )


def call_deepseek(api_key: str, prompt: str) -> tuple[dict[str, str], list[dict]]:
    """以 ChatDeepSeek 生成映射，返回 ({原文件名: 新文件名}, [必填缺失被跳过的条目])。"""
    llm = ChatDeepSeek(model=DEEPSEEK_MODEL, api_key=api_key, temperature=0)
    content = llm.invoke(prompt).content
    return _parse_result(content)


def _parse_result(content: str) -> tuple[dict[str, str], list[dict]]:
    """从返回文本提取 {原文件名:新文件名} 与 _errors 错误列表（容忍 ```json 代码块包裹）。

    设计理由：必填槽位取不到的文件不写入映射，模型改放在 _errors 键下，此处拆开返回，
    避免 _errors 被误当成一条映射去重命名。
    """
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
    errors = data.pop("_errors", None)
    if not isinstance(errors, list):
        errors = []
    return {str(k): str(v) for k, v in data.items()}, errors


_EXTRACT_INSTRUCTION = (
    "你是电影文件名解析助手。对每个文件名，提取其中的「中文名」和「英文名」："
    "中文名取文件名里的中文字段；英文名取文件名里的英文片名（去掉年份、分辨率、"
    "编码、音轨、字幕、发布组等噪音词）；两者都没有则该字段为空字符串。\n"
    "仅输出一个 JSON 字典：key 为原文件名，value 为 {\"zh\": 中文名, \"en\": 英文名}，"
    "不要输出任何其他文字或解释。"
)

_TV_EXTRACT_INSTRUCTION = (
    "你是电视剧文件夹名解析助手。对每个文件夹名，提取其中的「中文名」和「英文名」："
    "中文名取文件夹名里的中文字段；英文名取文件夹名里的英文片名（去掉年份、季、分辨率、"
    "编码、音轨、字幕、发布组等噪音词）；两者都没有则该字段为空字符串。\n"
    "仅输出一个 JSON 字典：key 为原文件夹名，value 为 {\"zh\": 中文名, \"en\": 英文名}，"
    "不要输出任何其他文字或解释。"
)


def extract_names(api_key: str, filenames: list[str], is_tv: bool = False) -> dict[str, dict]:
    """AI 从文件名/文件夹名提取 {zh, en}（作数据源查询词），供知识库扩充，非重命名。"""
    instr = _TV_EXTRACT_INSTRUCTION if is_tv else _EXTRACT_INSTRUCTION
    unit = "文件夹名" if is_tv else "文件名"
    lines = "\n".join(f"{i}. {n}" for i, n in enumerate(filenames, 1))
    llm = ChatDeepSeek(model=DEEPSEEK_MODEL, api_key=api_key, temperature=0)
    content = llm.invoke(instr + f"\n\n## 待解析{unit}\n{lines}").content
    return _parse_extract(content)


def _parse_extract(content: str) -> dict[str, dict]:
    """解析 extract_names 返回的 {文件名: {zh,en,finished}}，容忍代码块包裹。"""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"返回内容不是 JSON: {content[:200]}")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("返回内容不是字典")
    out: dict[str, dict] = {}
    for k, v in data.items():
        if isinstance(v, dict):
            out[str(k)] = {
                "zh": str(v.get("zh") or "").strip(),
                "en": str(v.get("en") or "").strip(),
                "finished": str(v.get("finished") or "").strip(),
            }
    return out

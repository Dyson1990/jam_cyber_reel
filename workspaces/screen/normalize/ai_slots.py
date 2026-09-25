"""screen AI 槽位补全 — 文本槽位提取（LLM）。

AI 只补全需要「理解文件名文本」的槽位（中文名/英文名/年份/版本信息/片源/字幕，
电视剧再加季集号/副标题），输出 JSON 槽位；全名拼装见 naming.py——技术槽位（分辨率…音轨数）
由 media_probe（PyAV）读取、扩展名取原文件，由 naming.assemble() 拼装，不再问 AI。
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

# 规则知识库：一条「标准格式」固定槽位顺序，其余规则只描述各文本槽位的来源与可空性。
# 技术槽位（分辨率…音轨数/字幕兜底/扩展名）不在此——由 media_probe + assemble 程序化补齐。

# 文本槽位规则（中文名/英文名/年份/版本信息/豆瓣评分/片源/字幕）电影与电视剧共享
_SLOT_RULES: list[dict[str, str]] = [
    {
        "topic": "中文名",
        "content": "来源=原文件名或知识库，必填。原文件名有中文名则提取；没有时取「## 知识库数据」的中文名；"
        "两者都没有则该文件跳过报错。",
    },
    {
        "topic": "英文名",
        "content": "来源=原文件名或知识库，必填。原文件名有英文名则提取；没有时取「## 知识库数据」的英文名；"
        "两者都没有则该文件跳过报错。空格改下划线 _；英文冒号（连其后空格）合并成一个中文冒号 ：；"
        "连字符/破折号（- – —）连两侧空格合并成一个连字符 -。",
    },
    {
        "topic": "年份",
        "content": "来源=原文件名或知识库，必填。原文件名有年份则用；没有时取「## 知识库数据」的年份；两者都没有则该文件跳过报错。",
    },
    {
        "topic": "版本信息",
        "content": "来源=原文件名，可空。统一译为中文「XXX版」：加长版/导演剪辑版/IMAX版/完整版/剧场版/重映版/"
        "特别版/未分级版/重制版/修正版；映射表之外忽略。",
    },
    {
        "topic": "豆瓣评分",
        "content": "来源=知识库，可空。取「## 知识库数据」评分的数字部分（如 8.5）；没有则留空。程序会加「豆」前缀。",
    },
    {
        "topic": "片源",
        "content": "来源=原文件名，可空。只取 BluRay/WEB-DL/BD/BDrip/ATVP/WEBRip；取不到留空。",
    },
    {
        "topic": "字幕",
        "content": "来源=原文件名，可空。CHS/中文字幕→中文字幕；中英字幕/中英双字/CHS.ENG→中英字幕；"
        "特效中英字幕→特效中英字幕；修正特效中英字幕→修正特效中英字幕；取不到留空"
        "（程序会读文件内封装字幕补 中文字幕/中英双字/其他字幕/无字幕）。",
    },
]

# ==================== 电影规则 ====================

RULES: list[dict[str, str]] = [
    {
        "topic": "总原则",
        "content": "只使用原文件名已有字段或「## 知识库数据」给出的字段，绝不臆造。中文名/英文名/年份必填；"
        "其余槽位缺值留空。分辨率/编码/位深/HDR/音频编码/声道/音轨数/字幕兜底/扩展名由程序读取媒体文件补齐，"
        "本步骤不输出。",
    },
    {
        "topic": "标准格式",
        "content": "最终文件名由程序按下序拼装（本步骤只填文本槽位，不填技术槽位）："
        "[中文名].[英文名].[年份][.版本信息][.豆瓣评分][.片源].[分辨率].[视频编码].[位深][.HDR]"
        "[.音频编码].[声道][.音轨数][.字幕].扩展名",
    },
    *_SLOT_RULES,
    {
        "topic": "示例",
        "content": "当幸福来敲门.The.Pursuit.of.Happyness.2006.BluRay.1080p.x265.10bit-DreamHD.mkv"
        "（知识库：中文名 当幸福来敲门）→ "
        "{\"当幸福来敲门.The.Pursuit.of.Happyness.2006.BluRay.1080p.x265.10bit-DreamHD.mkv\": "
        "{\"zh\":\"当幸福来敲门\",\"en\":\"The_Pursuit_of_Happyness\",\"year\":\"2006\",\"edition\":\"\",\"score\":\"\",\"source\":\"BluRay\",\"sub\":\"\"}}；"
        "利刃出鞘2.1080p.BD中英双字.mp4（知识库：英文名 Glass Onion、年份 2022、评分 6.6）→ "
        "{\"利刃出鞘2.1080p.BD中英双字.mp4\": "
        "{\"zh\":\"利刃出鞘2\",\"en\":\"Glass_Onion\",\"year\":\"2022\",\"edition\":\"\",\"score\":\"6.6\",\"source\":\"BD\",\"sub\":\"中英字幕\"}}；"
        "xxx.1080p.mkv（文件名与知识库都给不出中文名/英文名/年份）→ 不写入，报错：缺中文名/英文名/年份。",
    },
]

# ==================== 电视剧规则 ====================

TV_RULES: list[dict[str, str]] = [
    {
        "topic": "总原则",
        "content": "只使用原集文件名已有字段或「## 知识库数据」给出的字段，绝不臆造。标准化对象是每个「系列文件夹」"
        "内的集文件：中文名/英文名/年份以「## 知识库数据」该系列为准（必填）；季号/集号/副标题/版本信息/片源/字幕"
        "从原集文件名提取。分辨率/编码/位深/HDR/音频编码/声道/音轨数/字幕兜底/扩展名由程序读取媒体文件补齐，本步骤不输出。",
    },
    {
        "topic": "标准格式",
        "content": "电视剧三级结构由程序按下序拼装（本步骤只填文本槽位）："
        "系列文件夹=[中文名].[英文名]；季文件夹=S{两位季号}.[中文名].[英文名].[年份]；"
        "集文件=[中文名].[英文名].S{两位季号}E{两位集号}[_副标题][.版本信息][.豆瓣评分][.片源]"
        ".[分辨率].[视频编码].[位深][.HDR][.音频编码].[声道][.音轨数][.字幕].扩展名。",
    },
    {
        "topic": "季集号",
        "content": "季号/集号从原集文件名提取：S01E02 → season=01、episode=02；第2集 → season=01、episode=02；"
        "E03/EP03 → episode=03；02 → episode=02；完全取不到季集号则该集 season=01、episode 沿用数字序，"
        "仍取不到则跳过报错。季号/集号统一两位零填充（01、02）。",
    },
    {
        "topic": "副标题",
        "content": "来源=原集文件名或「## 知识库数据」，可空。原集文件名有副标题（如【Blood Ties】）则提取；"
        "「## 知识库数据」给了逐集副标题则以其为准（有中文优先用中文，否则用英文，其他语言不要）；"
        "两者都没有则留空。英文副标题空格改下划线 _；中文副标题保持原样。",
    },
    *_SLOT_RULES,
    {
        "topic": "示例",
        "content": "企鹅人.The_Penguin/企鹅人.The_Penguin.【Blood Ties】.2024.S01E06.1080p.mkv"
        "（知识库：中文名 企鹅人、英文名 The Penguin、逐季年份 2024、逐集副标题 S01E06=Blood Ties）→ "
        "{\"企鹅人.The_Penguin/企鹅人.The_Penguin.【Blood Ties】.2024.S01E06.1080p.mkv\": "
        "{\"zh\":\"企鹅人\",\"en\":\"The_Penguin\",\"year\":\"2024\",\"season\":\"01\",\"episode\":\"06\",\"subtitle\":\"Blood_Ties\",\"edition\":\"\",\"score\":\"\",\"source\":\"\",\"sub\":\"\"}}；"
        "茶杯头大冒险.The_Cuphead_Show/S01E02.1080p.mkv"
        "（知识库：中文名 茶杯头大冒险、英文名 The Cuphead Show、逐季年份 2022）→ "
        "{\"茶杯头大冒险.The_Cuphead_Show/S01E02.1080p.mkv\": "
        "{\"zh\":\"茶杯头大冒险\",\"en\":\"The_Cuphead_Show\",\"year\":\"2022\",\"season\":\"01\",\"episode\":\"02\",\"subtitle\":\"\",\"edition\":\"\",\"score\":\"\",\"source\":\"\",\"sub\":\"\"}}；"
        "xxx/abc.mkv（文件名与知识库都给不出中文名/英文名）→ 不写入，报错：缺中文名/英文名。",
    },
]

_JSON_INSTRUCTION = (
    "\n\n## 输出要求\n"
    "仅输出一个 JSON 字典：key 为原文件名，value 为槽位对象：\n"
    "{\"原文件名\": {\"zh\": 中文名, \"en\": 英文名, \"year\": 年份, \"edition\": 版本信息, \"score\": 评分数字, \"source\": 片源, \"sub\": 字幕}}\n"
    "zh/en/year 必填；edition/score/source/sub 取不到留空字符串 \"\"。\n"
    "必填槽位取不到的文件不要作为 key，改放入 \"_errors\" 键，值为数组，每项 {\"file\": 原文件名, \"reason\": 缺失说明}。\n"
    "不要输出任何其他文字或解释。"
)

_TV_JSON_INSTRUCTION = (
    "\n\n## 输出要求\n"
    "仅输出一个 JSON 字典：key 为原相对路径（=【系列文件夹】名 + \"/\" + 集文件名，集文件名按展示还原），value 为槽位对象：\n"
    "{\"原相对路径\": {\"zh\": 中文名, \"en\": 英文名, \"year\": 年份, \"season\": 季号两位, \"episode\": 集号两位, \"subtitle\": 副标题, \"edition\": 版本信息, \"score\": 评分数字, \"source\": 片源, \"sub\": 字幕}}\n"
    "zh/en/year/season/episode 必填；subtitle/edition/score/source/sub 取不到留空字符串 \"\"。\n"
    "必填槽位取不到的文件不要作为 key，改放入 \"_errors\" 键，值为数组，每项 {\"file\": 原相对路径, \"reason\": 缺失说明}。\n"
    "不要输出任何其他文字或解释。"
)

_FIX_JSON_INSTRUCTION = (
    "\n\n## 输出要求\n"
    "仅输出一个 JSON 字典：key 为原文件名，value 为要修正的槽位对象（只含要改的字段，未改的字段省略）：\n"
    "{\"原文件名\": {\"zh\": 中文名, \"en\": 英文名, \"year\": 年份, \"score\": 评分数字}}\n"
    "只修正「中文名/英文名/年份/豆瓣评分」，其余槽位程序保留原值，不要输出。无需修正的文件不要作为 key。\n"
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
    """组装「## 知识库数据」段落：条目号 + 中文名/英文名/年份/评分。"""
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
    return "\n\n## 知识库数据（条目号对应上方文件名序号）\n" + "\n".join(rows)


def build_prompt(
    filenames: list[str], limit: int | None = None, infos: dict[str, dict] | None = None,
    is_tv: bool = False,
) -> str:
    """检索相关规则 + 待标准化文件名（截断到 limit）+ 可选豆瓣信息（评分/年份）→ 组装提示词。"""
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


def _tv_info_section(infos: dict[str, dict] | None) -> str:
    """组装「## 知识库数据」段落：按系列文件夹给出中文名/英文名/逐季年份/季数。"""
    if not infos:
        return ""
    rows = []
    for folder, info in infos.items():
        parts = [
            f"{label}={info[key]}"
            for key, label in (("zh", "中文名"), ("en", "英文名"), ("year", "逐季年份"), ("seasons", "季数"))
            if info.get(key)
        ]
        eps = info.get("episodes")
        if isinstance(eps, dict) and eps:
            parts.append("逐集副标题=" + "、".join(f"{k}={v}" for k, v in eps.items()))
        if parts:
            rows.append(f"- 「{folder}」：{'，'.join(parts)}")
    if not rows:
        return ""
    return "\n\n## 知识库数据（系列文件夹 → 各字段）\n" + "\n".join(rows)


def _tv_episode_blocks(episodes: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """按系列文件夹分组压缩集文件，返回 ([(文件夹名, 展示块)], [无法总结被跳过的文件夹])，保持出现顺序。

    集文件名大多只有集号/集名/季号不同，公共前缀（片名/发布组）+公共后缀（画质/封装/扩展名）
    逐集重复，白白烧 token；这里前后缀各写一次，只列每集差异部分。无公共前后缀的文件夹
    （各集名称差距过大）无法总结，跳过并列入返回第二项，由调用方警告。
    """
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for ep in episodes:
        folder, _, name = ep.partition("/")
        if folder not in groups:
            groups[folder] = []
            order.append(folder)
        groups[folder].append(name)

    blocks: list[tuple[str, str]] = []
    skipped: list[str] = []
    for folder in order:
        names = groups[folder]
        if len(names) == 1:
            blocks.append((folder, f"【{folder}】\n1. {names[0]}"))
            continue
        toks = [n.split(".") for n in names]
        min_len = min(len(t) for t in toks)
        p = 0
        while p < min_len and all(t[p] == toks[0][p] for t in toks):
            p += 1
        s = 0
        while s < min_len - p and all(t[-1 - s] == toks[0][-1 - s] for t in toks):
            s += 1
        if p == 0 and s == 0:
            skipped.append(folder)
            continue
        prefix = (".".join(toks[0][:p]) + ".") if p else ""
        suffix = ("." + ".".join(toks[0][-s:])) if s else ""
        middles = [".".join(t[p:len(t) - s]) for t in toks]
        if not any(middles):
            skipped.append(folder)
            continue
        rows = "\n".join(f"{i}. {m}" for i, m in enumerate(middles, 1))
        blocks.append((folder, f"【{folder}】\n公共前缀：{prefix}\n公共后缀：{suffix}\n差异部分：\n{rows}"))
    return blocks, skipped


def tv_summarizable(episodes: list[str]) -> tuple[list[str], list[str]]:
    """判定每个系列能否总结，返回 (可总结系列名顺序, 无法总结被跳过的系列名)。"""
    blocks, skipped = _tv_episode_blocks(episodes)
    return [f for f, _ in blocks], skipped


def _tv_episode_lines(episodes: list[str]) -> tuple[str, list[str]]:
    blocks, skipped = _tv_episode_blocks(episodes)
    return "\n\n".join(b for _, b in blocks), skipped


def build_tv_prompt(
    episodes: list[str], infos: dict[str, dict] | None = None,
) -> tuple[str, list[str]]:
    """TV 集文件标准化提示词：输入 from 下每集相对路径，输出槽位对象。

    返回 (提示词文本, 无法总结被跳过的系列文件夹列表)；全部集文件都无法总结时提示词为空串。
    """
    context = "\n".join(f"- {d.page_content}" for d in _retrieve("\n".join(episodes), kind="tv"))
    lines, skipped = _tv_episode_lines(episodes)
    if not lines:
        return "", skipped
    prompt = (
        "你是电视剧集文件标准化助手，请严格依据下列规则处理。\n\n"
        f"## 规则\n{context}\n\n"
        f"## 待标准化集文件（按系列文件夹分组，【】内为文件夹名）\n{lines}"
        f"{_tv_info_section(infos)}{_TV_JSON_INSTRUCTION}"
    )
    return prompt, skipped


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
        "「中文名 / 英文名 / 年份 / 豆瓣评分」四个可查询补充槽位：依据「## 知识库数据」改正错误、"
        f"补上漏查（知识库数据有而{unit}缺的字段）；其余槽位（版本信息、片源、技术槽位、字幕等）一字不改；"
        f"无需修正的{unit}保持原名（不输出）。\n\n"
        f"## 槽位规范\n{context}\n\n"
        f"## 待检查{unit}\n{lines}{_info_section(names, infos)}{_FIX_JSON_INSTRUCTION}"
    )


def call_deepseek(api_key: str, prompt: str) -> tuple[dict, list[dict]]:
    """以 ChatDeepSeek 生成槽位映射，返回 ({原文件名: 槽位 dict}, [必填缺失被跳过的条目])。"""
    llm = ChatDeepSeek(model=DEEPSEEK_MODEL, api_key=api_key, temperature=0)
    content = llm.invoke(prompt).content
    return _parse_result(content)


def _parse_result(content: str) -> tuple[dict, list[dict]]:
    """从返回文本提取 {原文件名:槽位 dict} 与 _errors 错误列表（容忍 ```json 代码块包裹）。

    设计理由：必填槽位取不到的文件不写入映射，模型改放在 _errors 键下，此处拆开返回，
    避免 _errors 被误当成一条映射。value 非 dict（旧格式全名）一律丢弃。
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
    return {str(k): (v if isinstance(v, dict) else {}) for k, v in data.items()}, errors


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

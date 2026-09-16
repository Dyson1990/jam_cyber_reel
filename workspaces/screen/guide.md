# screen — 影视业务域

## 定位
影视业务域，对应 movie（电影）/ tv（电视剧）两个 Profile。
命名标准化用 AI（LangChain + DeepSeek），知识库用 chromadb 固化「中文名/英文名/年份/豆瓣评分」映射。

## 关联 Profile
- movie — 电影（默认 profile）
- tv — 电视剧

## 目录约定（from / to / root）
三条通用路径（统一保存在 `schema.py`，各功能页共享）：
- **from** — 网上下载、未经修改的原文件
- **to** — 经过文件名标准化的文件
- **root** — 文件名人工检查过的文件

数据流：from（下载原文件）→ 标准化 → to（已标准化）→ 人工检查 → root → AI 修正（最终打磨）。

「扫描」页把 from/to/root 三目录的**顶层**影视文件与压缩包写入 media 表，并记录每条记录的
来源（source=from/to/root）。「标准化」「知识库」不再自行扫盘，直接按来源从数据库取文件。

## 后端文件（workspaces/screen/）
- `schema.py` — 默认 schema（from/to/root 等跨功能参数 + table_schema/extra_config），
  功能页专属默认值从各文件夹的 `defaults.py` 合并进来
- `scan/sync.py` — 数据库同步：扫 from/to/root 顶层、记录来源
- `normalize/` — AI 命名/修正后端（ai_naming.py + defaults.py）
- `knowledge_base/` — chromadb 知识库（store.py + sources/ 各数据源）
- `screenshot/` — 截图采集（转发 core.screenshots）
- `overview/` — DeepSeek Key 管理（全站统一）

## 前端文件（ui/workspaces/screen/）
一页一文件，与后端文件夹对应：
- `scan.py` — 扫描（from/to/root + 对比差异 / 数据库同步）
- `knowledge_base.py` — 知识库（浏览 + AI 扩充，数据取自数据库）
- `normalize.py` — 标准化（映射命名 / AI 命名 / AI 修正）
- `screenshot.py` — 截图（root + count/moments）
- `overview.py` — 概览扩展（DeepSeek Key 卡片）
- `_shared.py` — 共享日志区 / 顶部电影电视剧单选 / 运行按钮

## 专用菜单
扫描 → 知识库 → 标准化 → 截图

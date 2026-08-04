---
name: explore
description: Explore literature by fetching papers from OpenAlex with multi-dimensional filters (ISSN, concept, author, institution, keyword, etc.) into an isolated database under data/explore/<name>/, with keyword search and agent-driven topic grouping of results. Use when the user wants to survey a journal, explore a research field, analyze an author's output, or do landscape analysis.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "research", "literature", "discovery", "openalex"]
---
# 多维文献探索

从 OpenAlex 拉取文献（支持多维过滤）到隔离的探索库，关键词检索 + agent 主题分组，用于文献调研。数据与主库完全隔离。

> **框架边界**：explore 只保留 `fetch` / `search`（FTS5 关键词）/ `list` / `info` 四个确定性原语，无嵌入、无自动聚类。**主题分组由 subagent 粗读接管**（见下方工作流）——真读标题摘要后的分组，强于原来的 BERTopic 无监督聚类。

## 执行逻辑

### 拉取论文

支持多种过滤维度，可任意组合：

```bash
# 按期刊 ISSN
scrinium explore fetch --issn <ISSN> --name <名称> [--year-range <起-止>]

# 按研究概念
scrinium explore fetch --concept <OpenAlex-concept-ID> --name <名称>

# 按作者
scrinium explore fetch --author <OpenAlex-author-ID> --name <名称>

# 按机构
scrinium explore fetch --institution <OpenAlex-institution-ID> --name <名称>

# 按关键词
scrinium explore fetch --keyword "acoustic metamaterial" --name <名称>

# 多维组合 + 高引过滤
scrinium explore fetch --institution I123 --year-range 2020-2025 --min-citations 50 --name <名称>

# 增量更新（追加新论文，DOI 去重）
scrinium explore fetch --issn 0022-1120 --name jfm --incremental
```

全部过滤参数：
- `--issn` — 期刊 ISSN
- `--concept` — OpenAlex concept ID
- `--topic-id` — OpenAlex topic ID
- `--author` — OpenAlex author ID
- `--institution` — OpenAlex institution ID
- `--keyword` — 标题/摘要关键词搜索
- `--source-type` — 来源类型（journal/conference/repository）
- `--oa-type` — 论文类型（article/review 等）
- `--min-citations` — 最小引用量
- `--year-range` — 年份过滤（如 2020-2025）
- `--name` — 探索库名称（默认从 filter 推导）
- `--incremental` — 增量更新模式

常用期刊 ISSN：
- JFM (Journal of Fluid Mechanics): 0022-1120
- PoF (Physics of Fluids): 1070-6631
- JCP (Journal of Computational Physics): 0021-9991
- IJMF (Int J Multiphase Flow): 0301-9322

### 搜索（关键词）

```bash
scrinium explore search --name <名称> "<查询词>" [--top N]
```

唯一的检索模式是 FTS5 关键词，**无 `--mode` 选项**。召回不足时用查询扩展（同义词、中英改写、缩写/全称）多搜几轮合并去重（见 `/search` skill 的查询扩展发现协议）。

### 列出所有探索库

```bash
scrinium explore list
```

### 查看探索库信息

```bash
scrinium explore info
scrinium explore info --name <名称>
```

## 主题分组工作流（subagent 接管）

explore 库没有 curator 标签体系，主题组织由 agent 完成：

1. 取待分组论文清单：全量分组时直接读 `data/explore/<名称>/papers.jsonl`（每行一篇，含标题/摘要）；或按若干主题关键词分轮 `explore search` 取子集
2. **并行派 subagent 分批粗读**（每批 30-50 篇，标题 + 摘要即可，互不重叠），每个 subagent 只带回每篇的「主题归属 + 一句话理由」
3. 主 agent 汇总分组结果，识别 5-15 个主题簇，写入 `workspace/<调研主题>/` 笔记（如 `topic-groups.md`）：每簇含主题名、代表论文、论文数、一句话概括
4. 分组结果可直接指导下一步：挑每簇核心论文入工作区（`/workspace`）、深读（`/show`）或写综述（`/literature-review`）

## 示例

用户说："帮我拉取 JFM 的全部论文"
→ 执行 `explore fetch --issn 0022-1120 --name jfm`

用户说："帮我看看 acoustic metamaterial 领域有哪些研究"
→ 执行 `explore fetch --keyword "acoustic metamaterial" --name acoustic-metamaterial`，再做主题分组：分批派 subagent 粗读 → 分组写入 workspace 笔记

用户说："拉取某机构近 5 年高引论文"
→ 执行 `explore fetch --institution I123 --year-range 2020-2025 --min-citations 50 --name inst-highcite`

用户说："在 JFM 里搜 drag reduction"
→ 执行 `explore search --name jfm "drag reduction"`

用户说："给刚拉的 jfm 库梳理一下研究主题"
→ 主题分组工作流：取论文清单 → 并行 subagent 分批粗读 → 汇总 5-15 个主题簇写入 `workspace/` 笔记

用户说："更新 JFM 探索库"
→ 执行 `explore fetch --issn 0022-1120 --name jfm --incremental`

用户说："我有哪些探索库"
→ 执行 `explore list`（或 `explore info`）

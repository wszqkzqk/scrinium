---
name: search
description: Search academic papers in the local Scrinium knowledge base. Keyword (FTS5) search with an agent-driven query-expansion discovery protocol (multi-reformulation parallel search, tag filters, citation-graph snowballing), author search, and federated search across main library, explore databases, and arXiv. Use when the user wants to find papers, look up literature, search by author, or search across multiple sources. For citation rankings and citation count updates, see the /citations skill.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "search", "papers", "fts5"]
---
# 文献搜索

在本地论文库中搜索文献。统一入口是 `scrinium search`：**唯一的检索模式是关键词（FTS5）**，框架内无向量召回；模糊语义发现由 agent 的**查询扩展发现协议**接管（见下）——用多改写并行搜 + 标签过滤 + 引用图滚雪球，不依赖任何向量模型即可达到与向量召回相当的覆盖。跨库搜索用 `--scope`。

## 执行逻辑

1. 解析用户输入，判断搜索方式：
   - 默认：`search`（关键词）。**不要试图加 `--mode`**，该选项已移除
   - 按作者搜索（"找某某的论文"）→ `search-author`
   - 按引用量排序（"引用最高的"、"top cited"）→ 转交 `/citations` skill
   - 跨库搜索（"也搜 arXiv"、"在 explore 库里找"、"全部来源"）→ `search --scope`
   - 模糊主题发现（"xx 相关的研究有哪些"）→ 启动**查询扩展发现协议**

2. 从用户输入中提取：
   - **查询词**：用户想搜索的内容
   - **返回数量**：用户指定的 `--top N`，未指定则使用默认值
   - **年份过滤**：`--year 2023`（单年）、`--year 2020-2024`（范围）、`--year 2020-`（起始年至今）
   - **期刊过滤**：`--journal "Fluid Mechanics"`（模糊匹配）
   - **类型过滤**：`--type review`（模糊匹配，常见值：`review`、`journal-article`、`book-chapter`）

3. 执行搜索命令：

**关键词搜索（唯一模式）：**
```bash
scrinium search "<查询词>" --top <N> [--year <Y>] [--journal <J>] [--type <T>]
```

**作者搜索：**
```bash
scrinium search-author "<作者名>" --top <N> [--year <Y>] [--journal <J>] [--type <T>]
```

> **引用量排序**：使用 `/citations` skill 中的 `scrinium top-cited` 命令。

**联邦搜索（跨库 + arXiv）：**
```bash
# 同时搜主库和 arXiv
scrinium search "<查询词>" --scope main,arxiv --top <N>

# 同时搜主库和 proceedings
scrinium search "<查询词>" --scope main,proceedings

# 同时搜主库和所有 explore 库
scrinium search "<查询词>" --scope main,explore:*

# 搜指定 explore 库
scrinium search "<查询词>" --scope explore:my-survey

# 仅搜 arXiv（在线查询，不需要本地数据）
scrinium search "<查询词>" --scope arxiv

# 全部来源
scrinium search "<查询词>" --scope main,proceedings,explore:*,arxiv
```

`--scope` 支持逗号分隔组合：`main`（主库）、`proceedings`（论文集子论文）、`explore:<名称>` 或 `explore:*`（explore 库）、`arxiv`（在线 arXiv API）。arXiv 结果会标注 `[已入库]` 表示该论文已在本地库中。

**标签检索（策展标签）：**
```bash
scrinium tags                                                       # 浏览词表（canonical + 别名 + 论文数）
scrinium search "<查询词>" --tag milestoning                        # 单标签过滤
scrinium search "<查询词>" --tag milestoning --tag drug-binding     # 多标签 AND
scrinium workspace search <名称> "<查询词>" --tag cryo-em            # 工作区内同样可用
```

标签来自人工/agent 策展的受控词表（`data/tags.yaml`），别名自动归一。标签本身已进入检索索引（搜 "force field" 能命中打了该标签的论文）。给论文打标签用 `/curate` skill。

4. 将搜索结果整理后呈现给用户。

5. **复杂查询**：当 CLI 参数组合无法满足需求时（如按一作姓氏首字母筛选、多条件交叉、自定义排序等），直接写 Python 读 `data/papers/*/meta.json` 做查询。JSON 关键字段：

```
title, authors, first_author, first_author_lastname, year, doi, journal,
abstract, paper_type, citation_count (dict: crossref/semantic_scholar/openalex),
ids, toc, l3_conclusion, tags
```

## 查询扩展发现协议（语义召回的接管形态）

单个查询词容易漏召回——这是关键词检索的固有短板，由 agent 用语言能力补足。对模糊/主题性查询，执行四步：

1. **多改写并行搜**：把用户意图改写为 2-4 个查询变体，**并行**执行多轮 `scrinium search`：
   - 中英互译（"减阻" ↔ "drag reduction"）
   - 同义词/近义词（"force field" ↔ "potential" ↔ "力场"）
   - 缩写/全称（"MD" ↔ "molecular dynamics"）
   - 上下位概念、方法名/体系名（"enhanced sampling" ↔ "metadynamics"/"umbrella sampling"）
2. **tags 过滤收窄**：先 `scrinium tags` 看词表，命中相关标签时用 `--tag` 做精确过滤（AND 语义可叠加）
3. **引用图滚雪球扩展**：对已命中的核心论文执行 `scrinium snowball <种子...> --top 20`（共享引用排序），把经典但关键词漏掉的文献捞回来；`references`/`cited-by`/`shared-references` 见 `/graph` skill
4. **理解筛排**：合并去重各轮结果，agent 凭对标题/摘要的理解筛掉伪命中、按真实相关度排序——这一步就是原语义排序的接管，且精度更高（真读过内容再排）

候选超过 30 条时派 subagent 筛选（AGENTS.md 纪律），只带回入选清单与一句话理由。

## 检索策略

- **结构化输出**：`search`/`show`/`workspace show`/`top-cited` 支持 `--json`，结果含 `dir_name`、`score` 等字段；需要程序化解析时用 `--json`，不要正则解析排版文本。
- **tags 是主题层**：`scrinium topics` 看主题分布，`--tag` 做主题内检索，二者配合覆盖"按研究方向浏览"的需求。

## Legacy 别名

以下旧命令仍可使用（隐藏别名，行为完全一致），但新工作请统一用 `search`：

| 旧命令 | 等价形式 |
|---|---|
| `fsearch <q> --scope S` | `search <q> --scope S` |

## 示例

用户说："帮我搜一下 turbulent boundary layer 相关的论文"
→ 执行 `search "turbulent boundary layer"`；召回不足时启动查询扩展协议（改写为 "wall-bounded turbulence"、"湍流边界层" 等并行搜）

用户说："找 Liao Z-M 的论文"
→ 执行 `search-author "Liao"`

用户说："我库里引用最高的论文有哪些"
→ 转交 `/citations` skill（使用 `top-cited` 命令）

用户说："2020年以后关于 drag reduction 的论文"
→ 执行 `search "drag reduction" --year 2020-`

用户说："JFM 上发的湍流论文"
→ 执行 `search "turbulence" --journal "Fluid Mechanics"`

用户说："库里都有哪些主题标签"
→ 执行 `scrinium tags`（词表）或 `scrinium topics`（主题分布）

用户说："找库里 milestoning 用在药物动力学上的论文"
→ 执行 `search "kinetics" --tag milestoning --tag drug-binding`

用户说："力场相关的论文有哪些"（标签已进索引，直接搜即可）
→ 执行 `search "force field"`；再对命中的核心论文 `snowball` 扩展一轮

用户说："帮我调研一下增强采样在 RNA 上的应用"（模糊主题发现）
→ 查询扩展协议全流程：改写 "enhanced sampling RNA" / "metadynamics RNA" / "增强采样" 并行搜 → `--tag` 过滤 → 对核心种子 `snowball` → 凭理解筛排后呈现

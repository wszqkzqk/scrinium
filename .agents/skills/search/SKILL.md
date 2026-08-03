---
name: search
description: Search academic papers in the local Scrinium knowledge base. Supports unified search (keyword + semantic fusion), keyword-only (FTS5), semantic-only (FAISS), author search, and federated search across main library, explore databases, and arXiv. Use when the user wants to find papers, look up literature, search by author, or search across multiple sources. For citation rankings and citation count updates, see the /citations skill.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "search", "papers", "semantic", "fts5"]
---
# 文献搜索

在本地论文库中搜索文献。统一入口是 `scrinium search`：用 `--mode` 选择检索模式（默认 keyword），用 `--scope` 做跨库联邦搜索。

## 执行逻辑

1. 解析用户输入，判断搜索模式：
   - 如果用户明确要求"语义搜索"、"向量搜索"，使用 `search --mode semantic`
   - 如果用户明确要求"关键词搜索"、"全文搜索"或"FTS"，使用 `search`（默认 `--mode keyword`）
   - 如果用户明确按作者搜索（如"找某某的论文"、"某某发表的"），使用 `search-author`
   - 如果用户要求按引用量排序（如"引用最高的"、"最经典的"、"top cited"），转交 `/citations` skill
   - **默认使用 `search --mode unified`（融合检索）**——同时执行 FTS5 关键词搜索和 FAISS 语义搜索，合并去重排序。两路都命中的论文排名靠前。向量索引不可用时自动降级为纯关键词。
   - 如果用户要求跨库搜索（如"也搜一下 arXiv"、"在 explore 库里也找找"、"也搜 proceedings"、"全部来源"、"联邦搜索"），使用 `search --scope`

2. 从用户输入中提取：
   - **查询词**：用户想搜索的内容
   - **返回数量**：用户指定的 `--top N`，未指定则使用默认值
   - **年份过滤**：`--year 2023`（单年）、`--year 2020-2024`（范围）、`--year 2020-`（起始年至今）
   - **期刊过滤**：`--journal "Fluid Mechanics"`（模糊匹配）
   - **类型过滤**：`--type review`（模糊匹配，常见值：`review`、`journal-article`、`book-chapter`）

3. 执行搜索命令：

**融合检索（默认）：**
```bash
scrinium search "<查询词>" --mode unified --top <N> [--year <Y>] [--journal <J>] [--type <T>]
```

**关键词搜索：**
```bash
scrinium search "<查询词>" --top <N> [--year <Y>] [--journal <J>] [--type <T>]
```

**语义搜索：**
```bash
scrinium search "<查询词>" --mode semantic --top <N> [--year <Y>] [--journal <J>] [--type <T>]
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

`--scope` 支持逗号分隔组合：`main`（主库融合搜索）、`proceedings`（论文集子论文）、`explore:<名称>` 或 `explore:*`（explore 库）、`arxiv`（在线 arXiv API）。提供 `--scope` 时忽略 `--mode`。arXiv 结果会标注 `[已入库]` 表示该论文已在本地库中。

**标签检索（策展标签）：**
```bash
scrinium tags                                                              # 浏览词表（canonical + 别名 + 论文数）
scrinium search "<查询词>" --mode unified --tag milestoning                 # 单标签过滤
scrinium search "<查询词>" --tag milestoning --tag drug-binding             # 多标签 AND
scrinium workspace search <名称> "<查询词>" --tag cryo-em                    # 工作区内同样可用
```

标签来自人工/agent 策展的受控词表（`data/tags.yaml`），别名自动归一。标签本身已进入检索索引（搜 "force field" 能命中打了该标签的论文）。给论文打标签用 `/curate` skill。

4. 将搜索结果整理后呈现给用户。融合检索结果中每项标注了匹配来源：
   - `both`：关键词和语义都命中（最相关）
   - `fts`：仅关键词命中
   - `vec`：仅语义命中

5. **复杂查询**：当 CLI 参数组合无法满足需求时（如按一作姓氏首字母筛选、多条件交叉、自定义排序等），直接写 Python 读 `data/papers/*/meta.json` 做查询。JSON 关键字段：

```
title, authors, first_author, first_author_lastname, year, doi, journal,
abstract, paper_type, citation_count (dict: crossref/semantic_scholar/openalex),
ids, toc, l3_conclusion, tags
```

## 检索策略

- **结构化输出**：`search`/`show`/`workspace show`/`top-cited` 支持 `--json`，结果含 `dir_name`、`score`、`match` 等字段；需要程序化解析时用 `--json`，不要正则解析排版文本。
- **多查询扩展**：单个查询词容易漏召回。对同一问题换 2-4 个角度各搜一轮（同义词、上下位概念、缩写/全称、方法名/体系名），合并去重——agent 的语言能力就是查询扩展层。
- **无嵌入部署**（`embed.provider=none`）：`--mode semantic` 不可用，`--mode unified`/`workspace search` 自动降级为纯关键词（结果标注"关键词"）。此时发现文献的主路径是：**多查询关键词 + `--tag` 过滤 + 引用图滚雪球**（`references`/`cited-by`/`shared-references`，见 `/graph` skill）。

## Legacy 别名

以下旧命令仍可使用（隐藏别名，行为完全一致），但新工作请统一用 `search`：

| 旧命令 | 等价形式 |
|---|---|
| `usearch <q>` | `search <q> --mode unified` |
| `vsearch <q>` | `search <q> --mode semantic` |
| `fsearch <q> --scope S` | `search <q> --scope S` |

## 示例

用户说："帮我搜一下 turbulent boundary layer 相关的论文"
→ 执行 `search "turbulent boundary layer" --mode unified`

用户说："用语义搜索找 drag reduction 的文献，给我前5篇"
→ 执行 `search "drag reduction" --mode semantic --top 5`

用户说："找 Liao Z-M 的论文"
→ 执行 `search-author "Liao"`

用户说："我库里引用最高的论文有哪些"
→ 转交 `/citations` skill（使用 `top-cited` 命令）

用户说："2020年以后关于 drag reduction 的论文"
→ 执行 `search "drag reduction" --mode unified --year 2020-`

用户说："JFM 上发的湍流论文"
→ 执行 `search "turbulence" --mode unified --journal "Fluid Mechanics"`

用户说："库里引用最高的 review 文章"
→ 转交 `/citations` skill（使用 `top-cited --type review` 命令）

用户说："帮我在 arXiv 上也搜一下 physics-informed neural network"
→ 执行 `search "physics-informed neural network" --scope main,arxiv`

用户说："所有来源都搜一下 drag reduction，包括 explore 库"
→ 执行 `search "drag reduction" --scope main,proceedings,explore:*,arxiv`

用户说："在我之前建的 wall-bounded-turbulence explore 库里搜 channel flow"
→ 执行 `search "channel flow" --scope explore:wall-bounded-turbulence`

用户说："连 proceedings 一起搜 granular damping"
→ 执行 `search "granular damping" --scope main,proceedings`

用户说："库里都有哪些主题标签"
→ 执行 `scrinium tags`

用户说："找库里 milestoning 用在药物动力学上的论文"
→ 执行 `search "kinetics" --mode unified --tag milestoning --tag drug-binding`

用户说："力场相关的论文有哪些"（标签已进索引，直接搜即可）
→ 执行 `search "force field" --mode unified`

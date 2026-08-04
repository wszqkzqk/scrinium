---
name: topics
description: Browse topic distribution in the paper library via curated tags. View the tag-topic overview, drill into a topic's papers, spot untagged papers and hand off to the /curate skill, and generate distribution charts via the /draw skill. Use when the user asks about research themes, topic distribution, or what areas the library covers.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "research", "topics", "tags"]
---
# 主题总览（标签即主题）

浏览论文库的主题分布。本框架中**策展标签（tags）即主题**：`scrinium topics` 是 `data/tags.yaml` 词表的主题化视图——按论文数排序展示各主题占比、列出未打标论文，并可钻取单个主题下的论文清单。

> **与 `scrinium tags` 的分工**：`tags` 面向词表管理（canonical / 别名 / 计数表），`topics` 面向主题浏览（分布 + 钻取）。两者底层共用同一套 tags 数据，不存在第二套主题模型。
>
> **词表治理**（合并近义标签、拆分过宽标签）不是本 skill 的职责——转交 `/curate` skill（通过 tags.yaml 别名归一）。

## 执行逻辑

1. 判断用户意图：
   - "主题分布"、"库里都有哪些方向" → 总览
   - "某个主题下有哪些论文" → 钻取
   - "画个主题分布图" → 总览取数 + `/draw` 出图
   - "哪些论文还没归主题" → 总览中的未打标计数 + `/curate` 接管
   - 默认展示总览

2. 执行命令：

**主题分布总览：**
```bash
scrinium topics [--json]
```
输出：论文总数、主题数，每个主题（tag）的论文数与占比（附词表描述），末尾提示未打标篇数。

**钻取单个主题：**
```bash
scrinium topics <tag> [--json]
```
`<tag>` 支持别名（自动归一为 canonical）。输出该主题下的论文清单（目录名 / 标题 / 年份，按年份倒序）。

3. 后续动作：
   - **未打标论文较多** → 告知用户并转交 `/curate` skill 批量打标（打标质量直接决定主题视图的完整性）
   - **主题下论文太多/太少、近义主题并存** → 这是词表健康问题，转交 `/curate` 做治理；本 skill 不做合并
   - **按主题建论文子集** → `scrinium workspace add <工作区> --tag <tag>` 把该主题全部论文加入工作区（见 `/workspace` skill）

## 分布图（交接 /draw）

`topics` 命令本身不出图。用户要可视化时：

1. `scrinium topics --json` 取主题分布数据
2. 转交 `/draw` skill，用 Mermaid（xychart / pie）或 Inkscape 生成柱状图 / 饼图
3. 图片输出到 `workspace/` 下

## 示例

用户说："帮我看看库里的主题分布"
→ 执行 `scrinium topics`

用户说："milestoning 这个方向有哪些论文"
→ 执行 `scrinium topics milestoning`

用户说："库里还有多少论文没归主题"
→ 执行 `scrinium topics`（看末尾未打标计数），不为零时建议转 `/curate`

用户说："给我画个主题分布图"
→ `scrinium topics --json` 取数，转交 `/draw` 出图

用户说："把 enhanced-sampling 主题的论文都收进一个工作区"
→ 执行 `scrinium workspace add <名称> --tag enhanced-sampling`

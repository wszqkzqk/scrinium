---
name: graph
description: Query citation graphs — view a paper's references, find which papers cite it, analyze shared references between multiple papers, and snowball-expand from seed papers to discover core literature. Use when the user asks about citation relationships, reference overlap, bibliographic connections, or entering a new field from a few seed papers.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "citations", "graph", "references"]
---
# 引用图谱查询

查看论文的参考文献、谁引用了此论文、多篇论文的共同参考文献，以及从种子论文出发的引用滚雪球发现。

> **别名**：`refs` / `citing` / `shared-refs` 分别是 `references` / `cited-by` / `shared-references` 的隐藏别名，行为完全一致；新工作请使用完整单词主名。

## 执行逻辑

### 查看论文的参考文献

```bash
scrinium references "<paper-id>" [--ws NAME]
```

### 查看谁引用了此论文

```bash
scrinium cited-by "<paper-id>" [--ws NAME]
```

### 共同参考文献分析

```bash
scrinium shared-references "<id1>" "<id2>" [--min N] [--ws NAME]
```

参数说明：
- `--min N` — 最少被 N 篇论文共同引用才纳入结果（默认 2）
- `--ws NAME` — 限定工作区范围

### 引用滚雪球（snowball）

```bash
scrinium snowball "<paper-id>" ["<paper-id>" ...] [--depth 1] [--top N] [--ws NAME] [--json]
```

从一篇或多篇种子论文出发，沿引用图自动扩张一层并按相关度排序：
- **向后**：种子的库内参考文献（关系标注 `refs`）
- **向前**：库内引用了种子的论文（关系标注 `citing`）
- **共享引用**：与种子共享 ≥1 条参考文献的库内论文（关系标注 `shared`）

打分规则（简单透明）：`score = 2×共享参考文献数 + 1×引用种子次数 + 1×被种子引用次数`，种子自身不计入候选。

参数说明：
- `--depth N` — 扩张深度（当前仅支持 1）
- `--top N` — 返回条数（默认 20）
- `--ws NAME` — 候选限定在工作区内
- `--json` — JSON 输出

**何时用**：进入一个新领域、手里只有一两篇种子论文时，快速定位该领域的核心文献。

**与 `shared-references` 的区别**：`snowball` 自动完成扩张 + 打分排序；`shared-references` 是手工的多点共引查询，不扩张也不排序。

## 前提条件

参考文献数据来自 Semantic Scholar，需先通过以下方式获取：
- 入库时自动拉取
- 已有论文运行 `refetch --all --force` 补拉
- 之后运行 `index --rebuild` 重建索引以更新 citations 表

> **空结果排查**：如果 `references`/`cited-by`/`snowball` 返回空结果，说明该论文的引用数据尚未获取。先运行 `refetch "<paper-id>"` 补拉，再 `index --rebuild` 更新 citations 表。

## 示例

用户说："这篇论文引了哪些文献"
→ 执行 `references "<paper-id>"`

用户说："哪些论文引用了这篇"
→ 执行 `cited-by "<paper-id>"`

用户说："这两篇论文有什么共同引用"
→ 执行 `shared-references "<id1>" "<id2>"`

用户说："从这篇综述出发，帮我找这个领域的核心文献"
→ 执行 `snowball "<paper-id>" --top 20`

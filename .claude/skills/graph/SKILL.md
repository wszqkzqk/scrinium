---
name: graph
description: Query citation graphs — view a paper's references, find which papers cite it, and analyze shared references between multiple papers. Use when the user asks about citation relationships, reference overlap, or bibliographic connections.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "citations", "graph", "references"]
---
# 引用图谱查询

查看论文的参考文献、谁引用了此论文、以及多篇论文的共同参考文献。

## 执行逻辑

### 查看论文的参考文献

```bash
scrinium refs "<paper-id>" [--ws NAME]
```

### 查看谁引用了此论文

```bash
scrinium citing "<paper-id>" [--ws NAME]
```

### 共同参考文献分析

```bash
scrinium shared-refs "<id1>" "<id2>" [--min N] [--ws NAME]
```

参数说明：
- `--min N` — 最少被 N 篇论文共同引用才纳入结果（默认 2）
- `--ws NAME` — 限定工作区范围

## 前提条件

参考文献数据来自 Semantic Scholar，需先通过以下方式获取：
- 入库时自动拉取
- 已有论文运行 `refetch --all --force` 补拉
- 之后运行 `index --rebuild` 重建索引以更新 citations 表

> **空结果排查**：如果 `refs`/`citing` 返回空结果，说明该论文的引用数据尚未获取。先运行 `refetch "<paper-id>"` 补拉，再 `index --rebuild` 更新 citations 表。

## 示例

用户说："这篇论文引了哪些文献"
→ 执行 `refs "<paper-id>"`

用户说："哪些论文引用了这篇"
→ 执行 `citing "<paper-id>"`

用户说："这两篇论文有什么共同引用"
→ 执行 `shared-refs "<id1>" "<id2>"`

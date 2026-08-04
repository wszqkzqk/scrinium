---
name: insights
description: Analyze research behavior data — search hot keywords, most-read papers, and reading trends — plus an agent-driven unread-recommendation workflow (recent reads → tag overlap + citation snowball → candidates). Use when the user wants to understand their reading habits, discover overlooked papers, or review recent research activity.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "research", "analytics", "habits", "discovery"]
---

# Research Observatory

分析用户的研究行为数据，发现阅读规律；「发现遗漏的相关论文」由 agent 的未读推荐工作流接管（近期阅读 → 标签重叠 + 引用滚雪球 → 候选清单）。

## 执行逻辑

```bash
scrinium insights [--days N]  # 默认分析过去30天
```

## 输出内容

1. **搜索热词 Top 10** — 最常出现在搜索查询中的词
2. **最常阅读论文 Top 10** — 按 `show` 命令调用次数统计
3. **阅读量趋势** — 按周统计的阅读事件数量（ASCII 柱状图）
4. **活跃工作区** — 当前工作区及其论文数量

## 未读推荐工作流（agent 接管）

"推荐一些我可能还没读过的相关论文"不再是框架内建输出，由 agent 执行三步：

1. **取近期阅读**：`scrinium insights --days 14`（或 `metrics --category read`）拿到最近阅读论文清单
2. **标签重叠扩展**：对每篇近期阅读 `scrinium show "<paper-id>" --layer 1` 看标签；用 `scrinium topics <tag>` / `search --tag <tag>` 找出同主题下未出现在阅读记录中的论文
3. **引用滚雪球扩展**：`scrinium snowball <近期阅读种子...> --top 20 --json`，共享引用越多的候选越可能是核心遗漏

汇总 2、3 的候选，剔除已读（对照阅读记录），凭标题/摘要理解筛排后呈现推荐清单。

## 前置条件

需要先累积一定量的使用数据（`search` 和 `show` 命令会自动记录事件到 `data/metrics.db`）。

## 示例

用户说："我最近都在看哪些方向的论文？"
→ 执行 `insights --days 30`

用户说："看看我过去一周的阅读记录"
→ 执行 `insights --days 7`

用户说："推荐一些我可能还没读过的相关论文"
→ 未读推荐工作流：`insights --days 14` 取近期阅读 → 标签重叠 + `snowball` 扩展 → 剔除已读、凭理解筛排后呈现

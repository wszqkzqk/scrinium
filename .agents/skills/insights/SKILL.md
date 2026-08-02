---
name: insights
description: Analyze research behavior data — search hot keywords, most-read papers, reading trends, and semantic neighbors you haven't read yet. Use when the user wants to understand their reading habits, discover overlooked papers, or review recent research activity.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "research", "analytics", "habits", "discovery"]
---

# Research Observatory

分析用户的研究行为数据，发现阅读规律和遗漏的相关论文。

## 执行逻辑

```bash
scrinium insights [--days N]  # 默认分析过去30天
```

## 输出内容

1. **搜索热词 Top 10** — 最常出现在搜索查询中的词
2. **最常阅读论文 Top 10** — 按 `show` 命令调用次数统计
3. **阅读量趋势** — 按周统计的阅读事件数量（ASCII 柱状图）
4. **推荐邻近论文** — 基于最近7天阅读记录的语义邻居，但尚未阅读过的（需嵌入后端；`embed.provider: none` 时会明确提示该功能不可用）
5. **活跃工作区** — 当前工作区及其论文数量

## 前置条件

需要先累积一定量的使用数据（search、usearch、vsearch 和 show 命令会自动记录事件到 `data/metrics.db`）。

## 示例

用户说："我最近都在看哪些方向的论文？"
→ 执行 `insights --days 30`

用户说："看看我过去一周的阅读记录"
→ 执行 `insights --days 7`

用户说："推荐一些我可能还没读过的相关论文"
→ 执行 `insights --days 14`（关注第4项"推荐邻近论文"输出）

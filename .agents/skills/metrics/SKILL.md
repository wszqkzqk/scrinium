---
name: metrics
description: View runtime timing metrics — pipeline step durations, API call timing, and search/read event history. Use when the user asks about performance statistics, slow steps, or recent activity timing.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["monitoring", "metrics", "performance", "timing"]
---
# 查看指标统计

查看框架运行时的**计时类指标**：pipeline 各步骤耗时、外部 API 调用耗时、搜索/阅读事件记录。框架内已无 LLM 调用，指标库不再产生 token 用量数据。

## 执行逻辑

**查看 pipeline 步骤耗时（默认类别 step）：**
```bash
scrinium metrics [--last 20]
```

**查看外部 API 调用耗时：**
```bash
scrinium metrics --category api --last 50
```

**查看搜索 / 阅读事件记录：**
```bash
scrinium metrics --category search --last 50
scrinium metrics --category read --last 50
```

**查看特定时间段：**
```bash
scrinium metrics --since 2026-03-01
```

**查看历史 LLM 事件（存量数据）：**
```bash
scrinium metrics --category llm --last 20
```
旧版本积累的 llm 类别事件仍保留在 `data/metrics.db` 中，可用该类别回看（含历史 token 列）；框架不会再写入新的 llm 事件。

## 典型用法

- **排查入库慢**：`metrics --category step` 看 `pipeline.*` 各步骤耗时分布（如 mineru 转换是大头）
- **排查 API 慢/失败**：`metrics --category api` 看 Crossref / S2 / OpenAlex 调用耗时与状态
- **回顾使用轨迹**：`metrics --category search` / `--category read`（与 `/insights` skill 的行为分析互补）

## 示例

用户说："看看最近入库各步骤花了多久"
→ 执行 `scrinium metrics --last 20`（默认 step 类别）

用户说："最近 API 调用有没有超时"
→ 执行 `scrinium metrics --category api --last 50`

用户说："我以前用了多少 token"
→ 执行 `scrinium metrics --category llm`（历史存量；说明框架已不产生新的 LLM 消耗）

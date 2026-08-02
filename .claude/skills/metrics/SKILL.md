---
name: metrics
description: View LLM token usage, API call timing, and runtime metrics. Use when the user asks about token consumption, API costs, or performance statistics.
version: 1.0.0
author: wszqkzqk/scrinium
license: MIT
tags: ["monitoring", "metrics", "llm", "tokens"]
---
# 查看指标统计

查看 LLM token 用量、API 调用耗时等运行指标。

## 执行逻辑

**查看最近 LLM 调用详情：**
```bash
scrinium metrics --last 20
```

**查看汇总统计：**
```bash
scrinium metrics --summary
```

**查看特定时间段：**
```bash
scrinium metrics --since 2026-03-01
```

**查看其他类别事件：**
```bash
scrinium metrics --category api --last 50
```

## 示例

用户说："我用了多少 token"
→ 执行 `metrics --summary`

用户说："看看最近的 LLM 调用"
→ 执行 `metrics --last 10`

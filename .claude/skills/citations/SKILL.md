---
name: citations
description: View top-cited papers ranking and refetch citation counts from APIs. Use when the user asks about highly cited papers, citation rankings, or wants to update citation data.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "citations", "bibliometrics", "impact"]
---
# 引用量查询

查看高引论文排行，或补查论文引用量数据。

## 执行逻辑

### 查看高引论文排行

```bash
scrinium top-cited [--top N] [--year RANGE] [--journal NAME] [--type TYPE]
```

### 补查引用量

```bash
# 补查所有缺失引用量的论文
scrinium refetch --all

# 强制重查所有
scrinium refetch --all --force

# 加速并发（默认 5）
scrinium refetch --all -j 10

# 补查单篇
scrinium refetch "<paper-id>"
```

## 示例

用户说："哪些论文引用最多"
→ 执行 `top-cited --top 20`

用户说："看看流体力学期刊的高引论文"
→ 执行 `top-cited --journal "Fluid Mech"`

用户说："帮我补查引用量"
→ 执行 `refetch --all`

用户说："2020 年以后的综述文章排行"
→ 执行 `top-cited --year 2020- --type review`

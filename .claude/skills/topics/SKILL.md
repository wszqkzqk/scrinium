---
name: topics
description: Explore topic distribution in the paper library using BERTopic clustering. Build/rebuild topic models, view topic overview, list papers in a topic, merge similar topics, and generate HTML visualizations. Use when the user asks about research themes, topic distribution, or wants to discover cross-domain connections.
version: 1.0.0
author: ZimoLiao/scholaraio
license: MIT
tags: ["academic", "research", "topic-modeling", "bertopic"]
---
# 主题探索

探索论文库的主题分布，发现跨领域关联。基于 BERTopic 聚类。

> 需要嵌入后端（`embed.provider` 为 local 或 openai-compat）才能构建/重建模型。无嵌入部署（`provider: none`）下已有模型仍可浏览，但无法重建——此时主题组织应改用策展标签体系（`/curate` skill + `scholaraio tags`）。

## 执行逻辑

1. 判断用户意图：
   - "建模"、"重建主题" → 构建/重建
   - "合并主题"、"压缩到N个" → 智能合并
   - "可视化"、"画图" → 生成 HTML
   - 查看某主题详情 → 主题查询
   - 查看 outlier → topic -1
   - 默认展示概览

2. 执行命令：

**构建/重建主题模型：**
```bash
scholaraio topics --build
scholaraio topics --rebuild [--min-topic-size N] [--nr-topics N]
```

**手动合并指定主题（格式: 逗号分隔同组ID，+分隔不同组）：**
```bash
scholaraio topics --merge "1,6,14+3,5"
```

**算法合并到 N 个主题：**
```bash
scholaraio topics --reduce <N>
```

**查看主题概览：**
```bash
scholaraio topics
```

**查看指定主题的论文：**
```bash
scholaraio topics --topic <ID> [--top N]
```

**生成 HTML 可视化（6 张图表）：**
```bash
scholaraio topics --viz
```

3. **智能合并流程**（当用户要求合并/压缩主题时）：
   a. 先执行 `topics` 获取所有主题概览
   b. 分析每个主题的关键词，判断哪些主题在学术上属于同一研究方向
   c. 生成合并方案
   d. 用 `--merge` 执行合并

## 示例

用户说："帮我看看库里的主题分布"
→ 执行 `topics`

用户说："主题2里有哪些论文"
→ 执行 `topics --topic 2`

用户说："帮我把相似的主题合并一下"
→ 先 `topics` 查看概览，分析关键词，再 `topics --merge "1,6,14+3,5"`

用户说："给我画个主题分布图"
→ 执行 `topics --viz`

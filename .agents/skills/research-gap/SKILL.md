---
name: research-gap
description: Identify research gaps and open questions from the literature in a workspace. Combines topic clustering, citation analysis, and cross-paper comparison. Use when the user wants to find unexplored areas, formulate research questions, or assess where the field is heading.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "research", "gap-analysis", "discovery"]
---
# 研究空白识别

从工作区文献中系统性地发现研究空白和开放问题。

> **路由**：如果目标是把文献组织成一篇完整的综述（空白识别只是其中一环），转交 `/literature-review` skill。

## 前提

用户必须指定一个**工作区名称**，且工作区中应有足够数量的论文（建议 10+ 篇）。
报告语言由用户指定（中文 / English）。

## 执行逻辑

### 1. 全局扫描

```bash
scrinium workspace show <name>               # 论文列表
scrinium topics                             # 主题（标签）分布总览
```

对工作区论文做 L2 扫描（标题 + 摘要），建立领域地图。`show` 命令会自动展示已有的 `notes.md` 历史笔记，优先复用已有发现。

### 2. 多维度分析

#### 维度 1：主题覆盖度
```bash
scrinium topics                             # 全库主题（标签）分布
scrinium topics <tag>                       # 某主题下的论文
```
工作区论文是否集中在某几个主题？哪些相关主题缺乏覆盖？

#### 维度 2：时间趋势
按年份统计工作区论文分布，识别：
- 哪些方向在近几年论文激增（热点）
- 哪些方向论文渐少（可能已成熟或被放弃）
- 哪些方向有早期工作但近年无跟进（潜在空白）

直接用 Python 读取 `data/papers/*/meta.json` 做统计分析。

#### 维度 3：方法论对比
扫描工作区论文的方法部分（L3-L4），绘制方法论矩阵：
```bash
scrinium show <paper-id> --layer 3          # 结论中通常提及方法
```
- 哪些方法被广泛使用？
- 哪些方法组合尚未被尝试？
- 某方法在 A 问题上成功，是否可迁移到 B 问题？

#### 维度 4：引用图谱空洞
```bash
scrinium shared-references "<id1>" "<id2>"   # 共同引用
scrinium references "<id>"                   # 参考文献
scrinium cited-by "<id>"                     # 被引论文
```
- 哪些论文互相引用但观点矛盾？（未解决的争议）
- 哪些论文被大量引用但缺乏后续验证/复现？
- 哪些关键参考文献不在工作区中？（可能是盲区）

#### 维度 5：论文自述的 Future Work
加载工作区中高引论文的 L3（结论），提取作者自己提出的未来方向：
```bash
scrinium show <paper-id> --layer 3
```
这些 future work 是否已有人做了？交叉搜索验证：
```bash
scrinium search "<future work 关键词>"
```

### 3. 输出报告

生成结构化的研究空白报告，保存到 `workspace/<name>/research-gaps.md`。

对每个发现的空白，按类型分类：

| 空白类型 | 含义 | 示例 |
|----------|------|------|
| **知识空白** | 某个现象/问题尚无人研究 | "高 Re 下的 X 效应尚未被测量" |
| **方法空白** | 已有结论但方法存在缺陷或局限 | "现有研究均为 RANS，缺乏 DNS 验证" |
| **矛盾空白** | 不同研究给出矛盾结论 | "A 组报告正效应，B 组报告负效应" |
| **迁移空白** | 某方法/发现尚未被推广到相关领域 | "该方法在 2D 有效，3D 尚未尝试" |
| **规模空白** | 只有小规模/受限条件的结果 | "仅低 Re 数据，工程 Re 下未验证" |

报告结构：
1. **领域现状概述**（2-3 段）
2. **已识别的研究空白**（按优先级排序）
   - 空白类型 + 描述
   - 支撑证据（哪些论文暗示了这个空白）
   - 潜在研究问题
   - 可行性评估（数据/方法/资源是否可及）
3. **未解决的争议**（如有）
4. **建议的下一步**

**量化辅助**：必要时编写 Python 代码从 meta.json 批量提取数据，做统计图表（年份分布、方法频次、参数范围覆盖等），用可视化支撑空白发现。

**分析笔记持久化**：对深度分析过的论文，**必须**通过 CLI 将关键发现写入笔记：
```bash
scrinium show "<paper-id>" --append-notes "## YYYY-MM-DD | <workspace> | research-gap
- 关键发现"
```

### 4. 互动讨论

报告生成后，主动与用户讨论：
- 哪些空白与用户的研究方向最相关？
- 是否需要补充更多文献来验证某个空白？
- 能否将某个空白细化为具体的研究问题和假设？

## 示例

用户说："帮我看看 drag-review 工作区里还有什么研究空白"
→ 全面扫描文献，多维度分析，生成研究空白报告

用户说："这些论文的 future work 都提了什么方向？有人做了吗？"
→ 提取各论文结论中的 future work，交叉搜索验证

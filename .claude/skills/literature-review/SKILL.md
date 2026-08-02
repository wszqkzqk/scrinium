---
name: literature-review
description: Write a literature review based on papers in a workspace. Covers topic organization, narrative structure, gap identification, and BibTeX export. Use when the user wants to draft a literature review, survey a research area, or summarize the state of the art.
version: 1.0.0
author: wszqkzqk/scrinium
license: MIT
tags: ["academic", "writing", "literature-review", "survey"]
---
# 文献综述写作

基于工作区中的论文，撰写结构化的文献综述。

> **路由**：如果目标是系统性识别研究空白和开放问题（而非撰写综述），转交 `/research-gap` skill。

## 前提

用户必须指定一个**工作区名称**。如果用户未指定：
1. 运行 `scrinium ws list` 列出已有工作区
2. 让用户选择或创建一个

综述输出写入 `workspace/<name>/` 目录。

## 执行逻辑

### 1. 了解写作需求

向用户确认：
- **综述主题**：围绕什么研究问题？
- **目标读者**：期刊论文的 Related Work？学位论文的文献综述章节？独立 review article？
- **语言**：中文 / English
- **篇幅**：大致字数或页数
- **风格参考**（可选）：用户可提供一篇范文或已有文本，你来分析其结构、叙述风格、引用密度、段落组织方式，然后仿照

### 2. 摸底文献范围

```bash
scrinium ws show <name>                    # 查看工作区论文列表
scrinium ws search <name> "<主题>"          # 范围内搜索
scrinium topics                             # 主题聚类概览（如已建模）
```

对工作区内论文做 L1-L2 快速扫描（标题 + 摘要），建立全局认知：
```bash
scrinium show <paper-id> --layer 2          # 逐篇扫描摘要
```

> 工作区论文超过 30 篇时，逐篇扫描应派 subagent 分批执行，只把结论摘要带回主 context，避免长列表和全文堆进主 context。

### 3. 构建综述骨架

根据文献内容，提出分组方案（按方法/时间线/研究问题/理论流派），形成章节大纲。向用户展示大纲并确认。

常见组织方式：
- **主题式**：按研究子问题分组（最常用）
- **时间线式**：按发展阶段梳理
- **方法论式**：按技术路线对比
- **争议式**：按观点分歧组织正反论证

### 4. 深度阅读关键论文

对每个章节的核心论文，用 `scrinium show` 阅读——已有的 `notes.md` 历史笔记会自动展示在标题之后，有则优先复用，避免重复劳动。

```bash
scrinium show <paper-id> --layer 3          # 结论（自动展示已有笔记）
scrinium show <paper-id> --layer 4          # 全文（仅关键论文）
```

分析完成后，**必须**通过 CLI 将关键发现写入笔记：
```bash
scrinium show "<paper-id>" --append-notes "## YYYY-MM-DD | <workspace> | literature-review
- 方法特点
- 核心贡献
- 与其他论文的关键对比"
```

**多模态分析**（MinerU 解析的论文保留了图表和公式）：
- 读取论文中的关键图表（`data/papers/<dir>/images/`），辅助理解实验结果和方法流程
- 分析论文中的数学公式（LaTeX），对比不同论文的建模方法差异
- 必要时编写 Python 代码做定量对比（如提取多篇论文报告的数值结果，绘制对比表格）

引用图谱辅助发现关联：
```bash
scrinium shared-refs "<id1>" "<id2>"        # 共同引用分析
scrinium refs "<id>"                        # 参考文献
scrinium citing "<id>"                      # 被引论文
```

### 5. 撰写综述

按确认的大纲逐节撰写。写作原则：

- **综合而非罗列**：每段围绕一个论点组织多篇文献，不是逐篇摘要
- **批判性视角**：指出方法局限、结论矛盾、实验条件差异
- **明确过渡**：章节间有清晰的逻辑衔接
- **引用格式**：正文中用 `(Author, Year)` 或 `Author (Year)`，与 BibTeX key 对应
- **如有风格参考**：严格仿照用户提供的范文的叙述节奏、引用密度、段落长度、术语习惯

每写完一节，暂停让用户审阅，再继续下一节。

### 6. 收尾

- 撰写综述开头（研究背景 + 综述范围 + 组织方式）和结尾（现状总结 + 研究空白 + 未来方向）
- 导出参考文献：
```bash
scrinium ws export <name> -o workspace/<name>/references.bib
```
- 定稿前用 `/citation-check` 检查正文中的 author-year 引用，避免幻觉引用和年份/作者错配
- 将综述正文保存到 `workspace/<name>/literature-review.md`（或用户指定的文件名）

## 学术态度

- 论文结论是作者的宣称，不是真理。综述应体现辩证思考。
- 当多篇论文对同一问题有不同结论时，主动指出分歧并分析可能原因。
- 高引用量 ≠ 正确。结合方法学质量、实验条件、可复现性综合评价。
- 明确区分「实验证据支持的结论」和「作者的推测/解读」。

## 示例

用户说："帮我写一篇关于湍流减阻的文献综述，基于 drag-review 工作区"
→ 查看 `ws show drag-review`，扫描论文，提出大纲，逐节撰写

用户说："我有一段范文，帮我按这个风格写"
→ 分析范文的结构和叙述特征，然后仿照该风格组织语言

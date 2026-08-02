---
name: paper-writing
description: Assist with writing sections of a research paper (Introduction, Related Work, Method, Results, Discussion, Conclusion). Leverages workspace papers for citations and evidence. Use when the user wants help drafting or revising specific paper sections.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "writing", "research", "sections"]
---
# 论文写作辅助

协助用户撰写研究论文的各个章节，基于工作区中的文献提供引用支持。

## 前提

用户必须指定一个**工作区名称**。如果用户未指定：
1. 运行 `scrinium ws list` 列出已有工作区
2. 让用户选择或创建一个

输出写入 `workspace/<name>/` 目录。

## 执行逻辑

### 1. 了解写作需求

向用户确认：
- **写哪个章节**：Introduction / Related Work / Method / Results / Discussion / Conclusion / Abstract
- **目标期刊/会议**：格式要求、篇幅限制
- **语言**：中文 / English
- **用户已有内容**：草稿、大纲、实验数据、图表
- **风格参考**（可选）：用户可提供同期刊/同领域的范文，你来分析其写作风格（句式结构、术语选择、段落节奏、引用方式、形式化程度），然后仿照

### 2. 论文分析笔记复用

用 `scrinium show` 阅读工作区论文时，已有的 `notes.md` 历史笔记会自动展示。有则优先复用，无需重复阅读全文。

分析完成后，**必须**通过 CLI 将新的关键发现写入笔记：
```bash
scrinium show "<paper-id>" --append-notes "## YYYY-MM-DD | <workspace> | paper-writing
- 关键发现"
```

### 3. 各章节写作策略

#### Introduction
1. 从宏观背景切入，逐步聚焦到具体问题
2. 引用工作区论文建立研究脉络：
   ```bash
   scrinium ws search <name> "<背景关键词>"
   scrinium show <paper-id> --layer 2      # 摘要
   ```
3. 明确指出现有工作的不足（research gap）
4. 阐述本文贡献

#### Related Work
本质上是聚焦版的文献综述，参考 `/literature-review` skill 的方法，但更紧凑：
- 按与本文的关系分组（而非按主题），每组指出与本文的异同
- 明确本文相对于 prior work 的改进

#### Method
1. 用户描述方法，你协助组织成清晰的叙述
2. 从工作区论文中找到可对比的方法：
   ```bash
   scrinium ws search <name> "<方法关键词>"
   scrinium show <paper-id> --layer 4      # 读全文了解方法细节
   ```
3. 确保符号定义一致、公式推导完整
4. **公式与图表**：读取参考论文中的数学推导（LaTeX）和方法示意图（`images/`），对比本文方法的异同，确保描述准确

#### Results / Discussion
1. 用户提供实验数据/图表
2. 从工作区中检索可对比的基线结果：
   ```bash
   scrinium ws search <name> "<实验条件>"
   scrinium show <paper-id> --layer 3      # 结论
   ```
3. **读图对比**：读取参考论文中的结果图表（`data/papers/<dir>/images/`），与用户的实验结果做定性/定量对比
4. **编写代码验证**：用 Python 做数据分析、统计检验、可视化——用计算结果支撑 Discussion 中的论点
5. Results：客观描述发现，引用图表
6. Discussion：解释原因、对比文献、讨论局限性

#### Conclusion
- 总结主要发现（不引入新内容）
- 简述局限性和未来方向

#### Abstract
- 最后写（需要全文定稿后）
- 包含：背景一句、问题一句、方法一句、主要结果两句、意义一句
- 字数严格遵循目标期刊要求

### 4. 引用管理

- 正文引用格式与目标期刊一致（通常 `\cite{key}` 或 `(Author, Year)`）
- **所有引用必须来自工作区中的真实论文**，绝不编造引用
- 如发现工作区缺少需要引用的论文，提醒用户补充：
  ```bash
  scrinium usearch "<关键词>"              # 全库搜索候选
  scrinium ws add <name> <paper-id>        # 添加到工作区
  ```
- 最终导出：
  ```bash
  scrinium ws export <name> -o workspace/<name>/references.bib
  ```

### 5. 输出

- 每完成一节保存到 `workspace/<name>/` 下（如 `introduction.md`、`related-work.md`）
- 或按用户要求合并为完整论文文件

## 写作原则

- **引用诚实**：只引用工作区中实际存在的论文。如果某个论点需要引用但库中没有对应文献，标注 `[CITATION NEEDED]` 而非编造。AI 生成文本中的引用有相当比例是幻觉或错配——必须用 `/citation-check` 验证
- **如有风格参考**：分析范文的句式长度、主被动语态比例、术语密度、段落结构，严格仿照
- **避免 AI 痕迹**：不用 "it is worth noting"、"in recent years, ... has garnered significant attention" 等套话；用具体、精确的学术表达
- **数据驱动**：Results 和 Discussion 中的每个断言都应有数据或引用支撑
- **计算验证**：当论文涉及数值结果或数学推导时，编写 Python 代码独立验证，不盲信手算或直觉

## 投稿前自查清单

完成全文后，按以下 6 项逐一检查：

1. **结构完整性**：各章节是否齐全？逻辑链条是否连贯？Introduction 提出的问题是否在 Conclusion 中回应？
2. **引用一致性**：正文引用与参考文献列表是否一一对应？有无遗漏或多余？用 `/citation-check` 验证
3. **图表质量**：每个图表是否在正文中被引用？图例是否清晰？坐标轴标签是否完整？
4. **数据可复现**：方法描述是否足够详细？关键参数是否都列出？
5. **语言质量**：术语是否全文一致？时态是否正确？用 `/writing-polish` 做最终润色
6. **格式合规**：是否满足目标期刊的字数、图片、参考文献格式要求？

## 示例

用户说："帮我写 Introduction，工作区是 my-paper"
→ 扫描 `ws show my-paper`，了解论文方向，询问研究问题，起草 Introduction

用户说："帮我按这篇 JFM 论文的风格写 Related Work"
→ 分析用户提供的范文风格，按该风格组织 Related Work

用户说："我有实验数据，帮我写 Results 和 Discussion"
→ 读取数据，检索工作区中的对比文献，撰写结果分析

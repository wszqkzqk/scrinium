---
name: deep-research
description: Run a multi-round deep literature investigation for an open research question. Orchestrates query decomposition, multi-source recall, citation-graph snowballing, batch deep reading with subagents, and evidence-matrix synthesis. Use when the user wants to systematically survey what is known about an open question (e.g. "how far has method X gotten on system Y"); for writing the final review use /literature-review, for dedicated gap analysis use /research-gap.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "research", "deep-research", "survey"]
---
# 深度文献调研

给一个开放性研究问题，做多轮「检索 → 精炼 → 阅读 → 综合」的系统调研：把问题拆成子问题，多路召回建池，沿引用图滚雪球扩张，批量深读积累证据，直到饱和后产出结论。

> **路由**：目标是写综述成稿（调研只是前置）→ `/literature-review`；专门识别研究空白 → `/research-gap`；单篇精读 → `/show`；已知主题的简单查找 → `/search`。

## 何时使用

- 开放性研究问题的系统调研，例如"X 方法在 Y 体系上做到什么程度了"、"Z 问题目前有哪些技术路线、各自证据如何"
- 进入一个新方向前的摸底：领域全景、核心文献、主要流派、未解决的争议
- 不适用：已有论文池、直接要成稿（转 `/literature-review`）；只要找空白（转 `/research-gap`）

## 前提

- 需要一个**调研主题名**（用作 `workspace/<主题>/` 目录和工作区名），用户未指定时你来拟一个简短英文 slug 并确认
- 本部署为无嵌入（`embed.provider=none`）：`usearch`/`ws search` 自动降级为纯关键词，`vsearch` 不可用，`explore search` 必须显式 `--mode keyword`。发现文献的主路径是 **多查询关键词 + `--tag` 过滤 + 引用图滚雪球**——本 skill 的工作流正是围绕这条路径设计的
- 全程维护一份**研究日志** `workspace/<主题>/research-log.md`：它是跨轮次、跨会话的记忆，中断续跑靠它恢复

## 工作流

### 阶段 1：问题分解

把开放问题拆成 3-7 个可检索的子问题/关键词面。常用维度组合：**对象（体系/材料）× 方法 × 任务/指标**。每个子问题配 2-4 个查询变体（同义词、缩写/全称、上下位概念、方法名/体系名）——agent 的语言能力就是查询扩展层。

创建研究日志 `workspace/<主题>/research-log.md`，初始结构：

```markdown
# <主题> 调研日志
- 起始日期：YYYY-MM-DD
- 研究问题：<用户问题原文>

## 子问题分解
- SQ1: <子问题> — 查询变体: q1a / q1b / q1c
- SQ2: ...

## 检索记录
| 日期 | 查询词 | 范围 | 命中 | 入选 |

## 论文池
- 工作区：<主题>；核心种子：<paper-id...>

## 子问题 × 证据矩阵
| 子问题 | 关键证据（paper-id） | 状态（充分/空缺/冲突） |

## 滚雪球记录
| 轮次 | 种子 | 新入核心 | 备注 |

## 饱和判断
- <每轮迭代后的结论>
```

### 阶段 2：多路召回

对每个子问题的每个查询变体，分别在以下来源检索：

```bash
# 主库（无嵌入时自动降级为纯关键词，属预期行为）
scrinium usearch "<查询词>" --top 20 --json
# 可加过滤：--year 2020-  --journal "<期刊名>"  --type review

# explore 外部库（主库覆盖薄的新领域）：先拉取，再关键词检索
scrinium explore fetch --keyword "<查询词>" --name <名称> [--year-range 2015-2025]
scrinium explore search --name <名称> "<查询词>" --mode keyword   # 无嵌入必须显式加

# arXiv 最新预印本（补主库的时效盲区）
scrinium arxiv search "<查询词>" [--category cond-mat.soft] [--sort recent]
```

需要程序化解析结果时用 `--json`，不要正则解析排版文本。每轮检索把**查询词、范围、命中数、入选数**记入日志的检索记录表——重复检索是饱和判断的依据。

### 阶段 3：初筛建池

对召回候选做 L1/L2 快筛（标题 + 摘要即可）：

```bash
scrinium show "<paper-id>" --layer 2 --json
```

候选超过 30 篇时**必须派 subagent 分批筛选**（AGENTS.md 纪律），每个 subagent 只带回「入选/排除 + 一句话理由」，不要把长列表堆进主 context。

入选种子建池：

```bash
scrinium ws init <主题>
scrinium ws add <主题> <paper-id...>
```

初筛结论（保留数量、排除理由的类别分布）记入研究日志。

### 阶段 4：滚雪球扩张

从池中挑 3-5 篇**核心种子**（领域综述、高被引、方法源头论文优先），沿引用图双向扩张：

```bash
scrinium snowball <种子1> <种子2> <种子3> --top 20 --json
# --depth 2     沿引用图多走一层（默认 1）
# --ws <主题>   把 ranked 候选直接写入工作区，省去手动 ws add
```

输出按共享引用数排序——共享引用越多，越可能是该领域的核心文献。对高分候选做 L2 快筛，确认相关后入池。每轮的种子、新入核心的论文记入日志的滚雪球记录。

滚雪球是无嵌入部署下最重要的召回补偿手段：关键词检索漏掉的经典文献，通常在几篇核心种子的共享引用里。

### 阶段 5：批量深读

对池内论文按子问题分工，派 subagent 读 L3/L4。纪律：

- **独立批次并行派发**，各 subagent 的论文集互不重叠
- 每个 subagent 的 prompt 必须包含：目标 paper-id（或目录路径）、要回答的具体问题、T2 笔记写入指令（参照 AGENTS.md 模板）
- 每个 subagent 只带 **T1 精炼结论**回主 context；分析过程（T3）留在 subagent 内部
- 每篇深读过的论文**必须**落 T2 笔记：

```bash
scrinium show "<paper-id>" --layer 3          # 深读（已有笔记会自动展示，优先复用）
scrinium show "<paper-id>" --append-notes "## YYYY-MM-DD | <主题> | deep-research
- 关键发现 1
- 关键发现 2"
```

`show` 会自动展示该论文的历史 `notes.md`，深读前先复用，结论可疑再回原文核对，避免重复劳动。

### 阶段 6：覆盖度追踪

在研究日志中维护「子问题 × 证据」矩阵，每批深读完成后更新：

- 每个子问题标注状态：**充分**（多篇独立证据）/ **空缺**（无证据或仅孤证）/ **冲突**（论文结论互相矛盾）
- 冲突要记录双方 paper-id 和可能原因（实验条件、方法假设、体系差异）——冲突本身就是调研发现
- 空缺子问题是下一轮检索的靶子：回到阶段 2 换查询角度专门补

可用策展标签辅助组织论文池：

```bash
scrinium tags                                   # 先看词表，优先复用已有标签，防止膨胀
scrinium tag "<paper-id>" <调研主题标签...>      # 打标
scrinium usearch "<查询词>" --tag <标签>         # 池内按标签过滤
```

批量打标遵循 `/curate` 纪律：克制造新标签，别把词表打爆。

### 阶段 7：饱和判断

每轮迭代后对照停止标准，**全部满足**才可进入产出：

- 连续两批滚雪球或新一轮多路检索**无新核心论文**（新入池的都是外围文献）
- 子问题 × 证据矩阵**无空缺**（冲突不算空缺，如实呈现即可）
- 共享引用集合收敛：`snowball` 的高分候选大多是已在池内的熟面孔

不满足则**回阶段 2 换角度**：换同义词/上下位词、换来源（主库 → explore/arXiv）、换种子（用新入池论文做种子再滚一轮）。每轮判断结论记入日志的饱和判断节。

### 阶段 8：综合产出

按用户需要产出（可组合）：

- **综述成稿** → 转交 `/literature-review`（基于本主题工作区）
- **调研报告** → 直接在 `workspace/<主题>/` 写 Markdown：领域现状、方法路线对比、证据矩阵、未解决争议、结论与建议
- **研究空白分析** → 转交 `/research-gap`

收尾：

```bash
scrinium ws export <主题> -o workspace/<主题>/references.bib   # 导出参考文献
```

- 正文中所有 author-year 引用**必须**过 `/citation-check`，避免幻觉引用和年份/作者错配
- 一切产出文件放 `workspace/<主题>/`，研究日志补记最终产出清单后收尾

## 纪律 checklist

每轮迭代和最终收尾前各过一遍：

- [ ] 研究日志更新了吗（检索记录、入池、证据矩阵、雪球轮次、饱和判断）
- [ ] 新读的论文都写 T2 notes 了吗
- [ ] subagent 并行派发且论文集互不重叠吗（>30 篇绝不堆进主 context）
- [ ] 产出文本的引用过了 `/citation-check` 吗
- [ ] 所有产出都在 `workspace/<主题>/` 下吗

## 示例

用户说："帮我调研一下 milestoning 在药物结合/解离动力学预测上做到什么程度了"
→ 完整流程：分解为「方法变体 / 体系与力场 / 结合解离时间预测精度 / 与 MSM、unbiased MD 的对比」等子问题，建研究日志 → 主库多查询召回 + arXiv 补新 → 初筛入 `ws init milestoning-kinetics` → 对 3-5 篇核心种子 `snowball --top 20 --json` → subagent 分批深读并写 notes → 更新证据矩阵 → 饱和后产出调研报告并过 citation-check

用户说："继续上次 milestoning 的调研"
→ 读 `workspace/milestoning-kinetics/research-log.md`：从证据矩阵的空缺子问题和上次未饱和的判断处接着跑（回阶段 2 补检索，或用新入池论文做种子回阶段 4），不从头再来

用户说："调研一下神经场势在反应动力学上的应用（我库里应该没什么相关文献）"
→ 主库召回稀薄时：`explore fetch --keyword "neural network potential" --name nnp-reaction` 拉外部库，`explore search --name nnp-reaction ... --mode keyword` 检索，叠加 `arxiv search` 补预印本，再进入建池与滚雪球

用户说："调研到的方法 A 和方法 B 结论矛盾，怎么回事？"
→ 在证据矩阵标冲突，派 subagent 对读两篇论文的 L3/L4（实验条件、假设、体系差异），结论记入矩阵和双方论文的 notes

用户说："把这个调研整理成一篇综述"
→ 饱和判断已通过、工作区已就绪，直接转交 `/literature-review`，研究日志作为背景材料

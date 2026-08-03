---
name: curate
description: Curate papers with tags in batch — build and maintain a healthy tag vocabulary, tag untagged papers via subagents, and review vocabulary quality. Use when the user wants to tag papers / batch-organize the library with tags / tidy up the tag vocabulary (especially when embedding retrieval is disabled and tags are the discovery mechanism).
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "papers", "curation", "tags"]
---
# 文献策展（标签）

用标签词表对论文库做人工/agent 策展：批量打标、维护词表健康度。嵌入检索被禁用时，标签是替代语义发现的核心机制——打标质量直接决定后续 `search --tag` 的可用性。

## 何时使用

- 用户要给论文（批量）打标签、整理标签体系
- 用户要清理词表：合并重复标签、拆分过宽标签
- 嵌入不可用，需要系统性建立可过滤的标签层

**不适用于：**

- 全文深度分析、精读——那是 `show` / `literature-review` 的事。策展只看 L1/L2（最多 L3），不为打标读全文
- 自动主题聚类——嵌入后端可用时，BERTopic 主题建模（`topics` skill）是自动聚类的另一条路；`curate` 是人工/agent 策展路线，两者互补

## 命令速查

| 命令 | 用途 |
|------|------|
| `scrinium tags [--json]` | 浏览词表：canonical 标签 + 别名 + 论文数 |
| `scrinium tag "<paper-id>"` | 无标签参数：显示该论文已有标签 |
| `scrinium tag "<paper-id>" <标签...>` | 加标签（别名自动归一为 canonical） |
| `scrinium tag "<paper-id>" <标签...> --remove` | 移除标签 |
| `scrinium show "<paper-id>" --layer 2` | 打标依据：L1 头部有"标签:"行，L2 有摘要 |
| `scrinium search "<查询词>" --tag <标签>` | 按标签过滤（多个 --tag 为 AND）；`--mode hybrid` 同 |
| `scrinium audit` | 报告 untagged（未打标）论文 |

词表持久化在 `data/tags.yaml`，结构：

```yaml
tags:
  force-field:
    aliases: [forcefield, ff]
    description: 力场方法与参数化
```

## 工作流

### 1. 拉取现有词表（打标前必读）

```bash
scrinium tags
```

**优先复用已有 canonical 标签**（含其别名），避免造出 `md` / `md-simulation` 这类近义重复。这一步的输出要摘要后写进 subagent prompt。

### 2. 圈定策展范围

- `scrinium audit` 报告 untagged 论文，作为默认待打标清单
- 或按用户指定：全库 / 某个 workspace / 新入库批次

### 3. 分批派 subagent 打标

每批 **15-20 篇**，批量 show 输出和论文列表都在 subagent 内消化，T1 只带回结果。每个 subagent 对每篇：

1. `scrinium tag "<paper-id>"` 先看已有标签，不重复打
2. `scrinium show "<paper-id>" --layer 2`（标题 + 摘要）；无摘要退回 `--layer 1`，仍不足以判断再看 L3 结论
3. 依据标题 + 摘要打 **2-5 个标签**，`scrinium tag "<paper-id>" <标签...>` 写入

### 4. 标签粒度指导

鼓励**多维度组合**，避免只有过粗的单一标签（如只打一个 `biology`）：

| 维度 | 示例 |
|------|------|
| 方法 | `milestoning`, `enhanced-sampling` |
| 体系/对象 | `rna-structure`, `cryo-em` |
| 任务 | `structure-prediction`, `free-energy` |
| 技术路线 | `deep-learning`, `md-simulation` |

命名约定：小写 kebab-case（`free-energy`，不是 `FreeEnergy`）。

### 5. 新标签提案（克制原则）

subagent **不得随意造标签**。遇到词表外概念先记录在"新标签提案"清单，批次结束后汇总给用户审核，确认后再批量注册。

注意与 CLI 行为的关系：`scrinium tag` 遇到新标签会**自动注册进词表并提示**——这是给临时单篇打标的便利；批量策展流程要求克制，新标签必须经用户审核后再用，防止词表在几百篇的批量操作中失控膨胀。

### 6. 收尾：词表健康度回顾

全部批次完成后：

1. 再跑 `scrinium tags`，检查：
   - **过宽**：挂论文过多、失去区分度 → 建议拆分
   - **过窄**：只挂 1 篇且非关键概念 → 建议合并
   - **疑似重复**：近义标签、别名未归一 → 提合并建议
2. 把审核通过的新标签清单和合并/拆分建议一并交用户确认
3. 用户确认合并后，用 `tag --remove` + `tag` 逐篇改挂（或直接编辑 `data/tags.yaml` 的别名做归一）

### 7. T2 笔记纪律

策展默认只读 L1/L2，**不需要**写笔记。但如果某篇深读超过 L2（看了 L3/L4）才定下标签，把关键发现写入 notes：

```bash
scrinium show "<paper-id>" --append-notes "## YYYY-MM-DD | curate | 策展深读
- 关键发现"
```

## Subagent 分派模板

```text
对以下 <N> 篇论文批量打标签：<paper-id 列表>

现有词表（必须优先复用，含别名）：
<scrinium tags 输出的摘要>

工作流程：
1. 每篇先 `scrinium tag "<paper-id>"` 看已有标签，再 `scrinium show "<paper-id>" --layer 2`（无摘要则 --layer 1）
2. 依据标题+摘要打 2-5 个标签，组合方法/体系/任务/技术路线多个维度，优先复用词表已有标签：
   scrinium tag "<paper-id>" <标签1> <标签2> ...
3. 词表外的新概念**不要直接打**，记录到"新标签提案"清单（含建议的 description）
4. 若某篇需读 L3/L4 才能判断，打标后必须写笔记：
   scrinium show "<paper-id>" --append-notes "## YYYY-MM-DD | curate | 策展深读
   - 发现"
5. 返回 T1：每篇的标签清单 + 新标签提案；不要包含阅读过程
```

## 示例

用户说："给库里没打标签的论文都打上标签"
→ 完整工作流：`scrinium tags` 拉词表 → `scrinium audit` 拿 untagged 清单 → 分批派 subagent → 收尾词表健康度回顾

用户说："把 rna-review 工作区的论文整理一下标签"
→ 范围限定到该 workspace，其余流程同上

用户说："给这篇打上 milestoning 和 enhanced-sampling"
→ 直接 `scrinium tag "<paper-id>" milestoning enhanced-sampling`（临时单篇，可走 CLI 自动注册）

用户说："看看现在有哪些标签"
→ 执行 `scrinium tags`

用户说："把这篇的 cryo-em 标签去掉"
→ 执行 `scrinium tag "<paper-id>" cryo-em --remove`

用户说："找 free-energy 方向做了深度学习的论文"
→ 执行 `scrinium search "深度学习" --tag free-energy --tag deep-learning`（AND 过滤）

## 纪律 checklist

- 打标前跑过 `scrinium tags`，已有标签（含别名）被优先复用
- 每篇 2-5 个标签、多维度组合，没有过粗的单一标签
- subagent 未擅自注册词表外新标签；新标签提案已汇总交用户审核
- 深读超过 L2 的论文已按 T2 纪律写 notes
- 收尾已跑 `scrinium tags` 回顾词表健康度，过宽/过窄/疑似重复标签已提合并建议

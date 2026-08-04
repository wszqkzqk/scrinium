---
name: enrich
description: Enrich paper metadata — agent-written L3 conclusions (subagent reads full text and writes meta.json directly), rule-based TOC extraction, and abstract backfill (regex + DOI fetch). Use when the user wants to extract conclusions, build TOC, or backfill missing abstracts. For citation count updates, see the /citations skill.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "papers", "metadata", "enrichment"]
---
# 富化论文内容

丰富论文元数据的三个职能，按接管路径分为两类：

- **结论（L3）**：需要理解——由 agent/subagent 精读全文后**直写 meta.json**（框架无 LLM，这是结论提取的正式形态）
- **目录（TOC）/ 摘要（abstract）**：规则可解——保留 `enrich toc` / `enrich abstract` 纯规则命令；规则未命中时输出 hint，由 agent 核对直写

> **写入即生效的约定**：agent 直写 meta.json 的 `l3_conclusion` / `toc` / `abstract` 字段后，运行 `scrinium index` 使其进入检索；`scrinium refresh` 不会覆盖 `toc*`/`l3_*` 键，agent 写入的内容是安全的。
>
> **引用量补查**：使用 `/citations` skill 中的 `scrinium refresh` 命令。

## 结论提取（L3，agent 直写工作流）

### 单篇

1. 派 subagent（或亲自）精读全文：

```bash
scrinium show "<paper-id>" --layer 4
```

> **subagent 类型**：写 meta.json 需要有写权限的 subagent（如 coder 型）；只读探索型 subagent 无法落盘——让它返回结论文本，由主 agent 写入（试点实证过的两种可行模式）。

2. 提炼结论段（研究结论、核心发现、局限性），用 Edit 工具写入论文目录 `meta.json`：

```json
"l3_conclusion": "This study demonstrates that ...",
"l3_extraction_method": "agent"
```

`l3_extraction_method: agent` 必须成对写入，标记结论来源。

3. 重建索引使结论可检索：

```bash
scrinium index
```

4. 验证：

```bash
scrinium show "<paper-id>" --layer 3
```

5. 结论提炼过程中的关键发现，按 T2 纪律同时沉淀到 notes（见 `/show` skill 的 `--append-notes`）。

### 批量

参照 `/curate` skill 的并行 subagent 模板：每批 15-20 篇、批次间论文集互不重叠，每个 subagent 对每篇执行「读 L4 → 提炼 → 直写 meta.json（含 `l3_extraction_method: agent`）」，只带回 T1 结论（成功/失败 + 一句话摘要）。全部批次完成后主 agent 统一跑一次 `scrinium index`。

**批量必须用有写权限的 subagent**（如 coder 型）；只读探索型 subagent 落不了盘。

批量打标式纪律同样适用：subagent prompt 必须含 paper-id 列表、写入字段约定、T2 notes 指令。

## 目录提取（TOC，纯规则命令）

```bash
scrinium enrich toc [<paper-id> | --all] [--force]
```

- 纯规则从 Markdown heading 结构推断 TOC，写入 meta.json 的 `toc` 字段
- 规则未命中时 CLI 输出 hint：`建议 agent 阅读全文后直接写 meta.json 的 toc 字段`——**见到 hint 即接管**：agent 读全文后自行整理章节结构直写 `toc`，然后 `scrinium index`
- agent 也可以对规则产出的 TOC 做核对修订（直写覆盖即可）

## 摘要补全（abstract，命令 + agent 核对）

```bash
scrinium enrich abstract [--dry-run] [--doi-fetch]
```

- 纯正则从 paper.md 提取缺失的 abstract；`--doi-fetch` 从出版商网页抓取官方 abstract（覆盖现有，需联网）
- 正则未命中的论文会列出并附 hint：`建议 agent 阅读原文后直接写 meta.json 的 abstract 字段`——按 hint 逐篇接管：读 L4 开头 → 直写 `abstract` → 全部完成后 `scrinium index`
- 对命令提取结果存疑的（截断、错位），agent 读原文核对后直写覆盖

## Legacy 别名

以下旧命令仍可使用（隐藏别名，行为完全一致），但新工作请统一用 `enrich` 子命令：

| 旧命令 | 等价形式 |
|---|---|
| `enrich-toc` | `enrich toc` |
| `backfill-abstract` | `enrich abstract` |

## 示例

用户说："帮我提取所有论文的结论"
→ 批量 agent 直写工作流：分批派 subagent 读 L4 → 直写 `l3_conclusion`（+`l3_extraction_method: agent`）→ 完成后 `scrinium index`

用户说："重新提取 Smith-2023-Survey 的目录"
→ 执行 `scrinium enrich toc "Smith-2023-Survey" --force`，确认输出 TOC 节数；规则未命中则按 hint 直写

用户说："补全摘要"
→ 执行 `scrinium enrich abstract`；对输出中列出的未命中论文，逐篇读原文直写 `abstract`，最后 `scrinium index`

用户说："这篇论文的结论是什么"
→ 先 `scrinium show "<paper-id>" --layer 3`；缺失（输出带 hint）时读 L4 提炼并直写，`index` 后再展示

用户说："补查引用量"
→ 转交 `/citations` skill（使用 `refresh` 命令）

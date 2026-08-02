---
name: show
description: View paper content at different detail levels. L1 (metadata), L2 (abstract), L3 (conclusion), L4 (full text). Use when the user wants to read a paper, see its abstract, conclusion, or full content.
version: 1.0.0
author: wszqkzqk/scrinium
license: MIT
tags: ["academic", "papers", "reading", "content"]
---
# 查看论文内容

按分层结构查看指定论文的内容。支持 L1（元数据）、L2（摘要）、L3（结论）、L4（全文）四个层次。

## 执行逻辑

1. 解析用户输入，提取：
   - **paper-id**：论文标识符（目录名 / UUID / DOI 均可）
   - **layer**：查看层次（1-4），默认 `--layer 2`（输出包含 L1 元数据 + L2 摘要）

2. 如果用户不确定论文 ID，先用 `/search` 帮用户找到目标论文。

3. 执行查看命令：

```bash
scrinium show "<paper-id>" --layer <N>
scrinium show "<paper-id>" --layer <N> --json   # 结构化输出（含 dir_name/notes 字段），需要程序化解析时使用
```

4. 将内容格式化后展示给用户。对于 L4 全文，如果内容过长，先展示摘要并询问用户是否需要完整内容。

## 层次说明

| 层 | 内容 | 说明 |
|----|------|------|
| L1 | 元数据 | title, authors, year, journal, doi, tags（标签） |
| L2 | 摘要 | abstract |
| L3 | 结论 | conclusion（需先运行 enrich-l3） |
| L4 | 全文 | 完整 markdown |

## 示例

用户说："看一下 Smith-2023-TransformerSurvey 这篇的摘要"
→ 执行 `show "Smith-2023-TransformerSurvey" --layer 2`

用户说："给我看 Zhang-2024-LLM 的全文"
→ 执行 `show "Zhang-2024-LLM" --layer 4`

用户说："这篇论文的结论是什么"（上下文中已有论文 ID）
→ 执行 `show "<paper-id>" --layer 3`

## T2 笔记集成

`show` 命令会自动展示该论文已有的 agent 笔记（`notes.md`）。笔记来自之前的分析会话，包含已提取的关键发现。

**读取规则**：
- 调用 `show` 时如果论文有 `notes.md`，内容会显示在标题之后、正文之前
- Agent 应优先利用笔记中的现有信息，避免重复分析

**写入规则**：
- 当 agent（或 subagent）通过 `show` 阅读论文并进行了分析，**必须**将值得跨会话保留的发现写入 `notes.md`：
```bash
scrinium show "<paper-id>" --append-notes "## 2025-03-25 | ghia-cavity | 参数提取
- 收敛判据：RMS 残差 < 1e-4
- Re=400 用 257x257 网格
- dt=inf for Re<=3200, dt=0.1 for Re=10000"
```
- 笔记格式：`## YYYY-MM-DD | workspace/任务来源 | 分析类型`

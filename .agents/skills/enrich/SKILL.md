---
name: enrich
description: Enrich paper metadata using LLM extraction. Extract table of contents (TOC), conclusions (L3), and backfill abstracts. Use when the user wants to extract conclusions, build TOC, or backfill missing abstracts. For citation count updates, see the /citations skill.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "papers", "metadata", "enrichment", "llm"]
---
# 富化论文内容

通过 LLM 提取论文的目录结构（TOC）或结论段（L3），丰富论文元数据。

> **注意**：`import-endnote` / `import-zotero` 导入时默认自动执行 toc + l3 + abstract backfill。以下命令用于**选择性富化**（如重新提取、补充特定论文、或处理全库）。
>
> **引用量补查**：使用 `/citations` skill 中的 `scrinium refetch` 命令。

## 执行逻辑

1. 解析用户意图：
   - **提取目录**：使用 `enrich-toc`
   - **提取结论**：使用 `enrich-l3`
   - **补全摘要**：使用 `backfill-abstract`（从 .md 提取 + LLM 校验）

2. 确定处理范围：
   - 指定论文 ID → 处理单篇
   - 用户说"全部" → 使用 `--all`
   - 可选 `--force` 覆盖已有结果

> 批量模式说明：
> - `--all` 会按 `config.llm.concurrency` 做多篇并发处理
> - 并发只发生在“论文之间”，单篇内部提取逻辑不拆分并发
> - 批量模式会对单篇失败自动做指数退避重试

3. 执行命令：

**提取目录：**
```bash
scrinium enrich-toc [<paper-id> | --all] [--force] [--inspect]
```

**提取结论：**
```bash
scrinium enrich-l3 [<paper-id> | --all] [--force] [--inspect] [--max-retries N]
```

**补全摘要：**
```bash
scrinium backfill-abstract [--dry-run] [--doi-fetch]
```

参数说明：
- `--inspect` — 展示提取过程详情（调试用）
- `--max-retries N` — L3 单篇提取最大重试次数（默认 2）；`--all` 时也作为每篇论文的批量重试预算
- `--doi-fetch` — 从出版商网页抓取官方 abstract（覆盖现有，需联网）

4. 展示处理结果。
   - `enrich-toc` 会显示开始提取、是否成功、以及提取出的 TOC 节数
   - 单篇处理会打印该篇的提取进度与结果
   - 批量处理会显示并发 worker 数，以及最终的成功 / 失败 / 跳过汇总

## 示例

用户说："帮我提取所有论文的结论"
→ 执行 `enrich-l3 --all`

用户说："重新提取 Smith-2023-Survey 的目录"
→ 执行 `enrich-toc "Smith-2023-Survey" --force`

用户说："帮我看看这篇论文 TOC 提取成功没有"
→ 执行 `enrich-toc "<paper-id>" --force`，并根据终端输出确认 `TOC 提取完成: N 节`

用户说："补全摘要"
→ 执行 `backfill-abstract`，然后提示 `embed --rebuild`

用户说："补查引用量"
→ 转交 `/citations` skill（使用 `refetch` 命令）

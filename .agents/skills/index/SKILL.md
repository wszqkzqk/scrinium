---
name: index
description: Rebuild the FTS5 full-text search index. Use when the user wants to update or rebuild the search index after metadata changes or direct meta.json edits.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "search", "indexing", "fts5"]
---
# 重建索引

重建 FTS5 全文检索索引。框架只有这一种索引（无向量索引）；meta.json 的任何变更（命令写入或 agent 直写）都要经过索引才会进入检索。

## 执行逻辑

**更新 FTS5 全文索引（增量）：**
```bash
scrinium index
```

**重建 FTS5 全文索引（清空后重建）：**
```bash
scrinium index --rebuild
```

**等价形式（pipeline 预设）：**
```bash
scrinium pipeline reindex   # = index 步骤
```

## 何时需要

- 入库 / 导入新论文后（pipeline 的 `ingest`/`full` 预设已含 index 步骤，通常无需手动）
- **agent 直写 meta.json 后**（`abstract`/`toc`/`l3_conclusion`/`translations` 等字段）——必须跑一次 `scrinium index`，直写内容才可检索
- `repair` / `rename` / 批量打标（`tag`）后
- 检索结果与 meta.json 内容明显不一致时，用 `--rebuild`

## 示例

用户说："重建索引"
→ 执行 `scrinium index --rebuild`

用户说："我刚改了 meta.json，怎么搜不到"
→ 执行 `scrinium index`（增量即可）

用户说："只更新新入库那几篇的索引"
→ 执行 `scrinium index`（增量更新是默认行为）

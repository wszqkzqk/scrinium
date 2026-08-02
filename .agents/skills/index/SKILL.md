---
name: index
description: Rebuild FTS5 full-text search index or FAISS semantic vector index. Use when the user wants to update or rebuild search indexes after metadata changes.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "search", "indexing", "fts5"]
---
# 重建索引

重建 FTS5 全文检索索引或 FAISS 语义向量索引。

## 执行逻辑

**更新 FTS5 全文索引（增量）：**
```bash
scrinium index
```

**重建 FTS5 全文索引：**
```bash
scrinium index --rebuild
```

**更新语义向量索引（增量）：**
```bash
scrinium embed
```

**重建语义向量索引：**
```bash
scrinium embed --rebuild
```

**两者都更新：**
```bash
scrinium pipeline reindex
```

## 示例

用户说："重建索引"
→ 执行 `pipeline reindex`

用户说："只重建全文索引"
→ 执行 `index --rebuild`

用户说："更新向量"
→ 执行 `embed`

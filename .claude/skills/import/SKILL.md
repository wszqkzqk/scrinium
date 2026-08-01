---
name: import
description: Import papers from external reference managers (Endnote XML/RIS, Zotero Web API or local SQLite), or attach a PDF to an existing paper. Handles PDF matching, MinerU conversion, metadata enrichment, and index updates. Use when the user wants to import their existing library from Zotero, Endnote, attach/add a PDF to a paper, or supplement a paper with its PDF.
version: 1.0.0
author: ZimoLiao/scholaraio
license: MIT
tags: ["academic", "papers", "import", "zotero", "endnote"]
---
# 导入外部文献管理工具数据 / 补充 PDF

支持从 Endnote / Zotero 批量导入，或为已入库论文单独补充 PDF（`attach-pdf`）。

## Endnote 导入

支持 Endnote 导出的 XML 和 RIS 格式文件。

```bash
# 完整导入：元数据 + PDF 匹配 + MinerU 批量转换 + enrich (toc/l3/abstract) + embed + index
scholaraio import-endnote <file.xml>

# 多文件导入
scholaraio import-endnote file1.xml file2.ris

# 仅导入元数据和 PDF，跳过 MinerU 转换和 enrich
scholaraio import-endnote <file.xml> --no-convert

# 预览模式
scholaraio import-endnote <file.xml> --dry-run

# 离线模式
scholaraio import-endnote <file.xml> --no-api
```

### PDF 自动匹配

对 Endnote XML 文件，自动解析 `internal-pdf://` 链接，从 `<library>.Data/PDF/` 目录匹配 PDF：
- 多个 PDF 时自动排除 SI/补充材料
- 默认通过 MinerU 批量转换为 paper.md

### 导入后自动处理

默认行为（不带 `--no-convert`）下，导入完成后自动执行完整 pipeline：
1. **批量 PDF→MD**：云端模式使用 `convert_pdfs_cloud_batch()` 批量转换（批次大小由 `config.yaml` `ingest.mineru_batch_size` 控制，默认 20）
2. **Abstract 补全**：从 markdown 中提取缺失的摘要
3. **TOC + L3 提取**：LLM 提取目录结构和结论段
4. **Embed + Index**：更新语义向量和全文索引

使用 `--no-convert` 跳过以上全部后处理（仅导入元数据 + PDF 复制 + embed + index）。

## Zotero 导入

支持 Web API 和本地 SQLite 两种模式。

### Web API 模式

```bash
# 列出 collections
scholaraio import-zotero --api-key KEY --library-id ID --list-collections

# 完整导入
scholaraio import-zotero --api-key KEY --library-id ID

# 仅导入指定 collection
scholaraio import-zotero --api-key KEY --library-id ID --collection COLLECTION_KEY

# 导入后将 collections 创建为工作区
scholaraio import-zotero --api-key KEY --library-id ID --import-collections
```

### 本地 SQLite 模式

```bash
scholaraio import-zotero --local /path/to/zotero.sqlite
```

### 配置文件（可选）

在 `config.local.yaml` 中配置 Zotero 凭据：

```yaml
zotero:
  api_key: "your-zotero-api-key"
  library_id: "your-library-id"
```

## 补充 PDF（单篇）

```bash
scholaraio attach-pdf <paper-id> <path/to/paper.pdf>
```

自动调用 MinerU 转换 PDF → markdown，补全缺失的 abstract，增量更新 embed + index。

## 批量补转 PDF（已入库论文）

对已入库但缺少 paper.md 的论文（如首次导入时用了 `--no-convert`），可通过 Python 调用批量转换：

```python
from scholaraio.config import load_config
from scholaraio.ingest.pipeline import batch_convert_pdfs

cfg = load_config()
stats = batch_convert_pdfs(cfg, enrich=True)
```

自动扫描 `data/papers/` 中有 PDF 无 paper.md 的论文，云端模式使用批量 API 转换，完成后运行 abstract backfill + toc + l3 + embed + index。

## 示例

用户说："我把 Endnote 库导出来了，帮我导入"
→ 执行 `import-endnote <file.xml>`

用户说："从 Zotero 导入我的文献库"
→ 执行 `import-zotero --local /path/to/zotero.sqlite`（本地模式；有 API 凭据时用 Web API 模式）

用户说："先看看会导入什么，别真动"
→ 执行 `import-endnote <file.xml> --dry-run`

用户说："只导元数据，PDF 先不转"
→ 执行 `import-endnote <file.xml> --no-convert`

用户说："这篇论文刚拿到 PDF，帮我补上"
→ 执行 `attach-pdf <paper-id> <path/to/paper.pdf>`

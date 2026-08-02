---
name: export
description: Export papers from the knowledge base to standard citation formats (BibTeX, RIS, Markdown reference list) or export any Markdown content as a Word DOCX file. Supports exporting all papers, specific papers, or filtered by year/journal. Use when the user needs citation files, wants to import into Zotero/Endnote/Mendeley, needs a reference list for writing, or wants to share a document as Word.
version: 1.0.0
author: ZimoLiao/scholaraio
license: MIT
tags: ["academic", "bibtex", "citations", "export", "docx", "ris"]
---
# 导出论文与文档

将本地论文库导出为标准引用格式，或将任意 Markdown 内容转换为 Word 文件。

## 支持的导出格式

| 格式 | 命令 | 用途 |
|------|------|------|
| BibTeX `.bib` | `export bibtex` | LaTeX 写作引用 |
| RIS `.ris` | `export ris` | Zotero / Endnote / Mendeley 导入 |
| Markdown 文献列表 | `export markdown` | 直接粘贴到文档、综述草稿 |
| Word DOCX | `export docx` | 分享给同事、导师，任意 Markdown 内容 |

---

## BibTeX 导出

```bash
# 导出全部论文到屏幕
scholaraio export bibtex --all

# 导出全部论文到文件
scholaraio export bibtex --all -o workspace/library.bib

# 导出指定论文（标识符支持目录名 / UUID / DOI，与 show 一致）
scholaraio export bibtex "Smith-2023-Turbulence" "Doe-2024-DNS"
scholaraio export bibtex "10.1038/s41467-022-28817-4"

# 按年份筛选导出
scholaraio export bibtex --all --year 2020-2024 -o workspace/recent.bib

# 按期刊筛选导出
scholaraio export bibtex --all --journal "Fluid Mechanics" -o workspace/jfm.bib
```

## RIS 导出（Zotero / Endnote / Mendeley）

```bash
# 导出全部论文
scholaraio export ris --all -o workspace/library.ris

# 导出指定论文
scholaraio export ris "Smith-2023-Turbulence" "Doe-2024-DNS" -o workspace/refs.ris

# 按年份筛选
scholaraio export ris --all --year 2022-2024 -o workspace/recent.ris
```

导出后可直接在 Zotero 中：File → Import → 选择 .ris 文件

## Markdown 文献列表导出

### 内置格式（--style）

| 格式名 | 说明 | 典型场景 |
|--------|------|----------|
| `apa`（默认） | APA 7th 作者-年份 | 社科、心理、教育 |
| `vancouver` | Vancouver/ICMJE 编号 | 医学、生命科学 |
| `chicago-author-date` | Chicago 17 作者-年份 | 人文、社科 |
| `mla` | MLA 9th | 文学、语言学 |
| `<自定义>` | 期刊专属格式 | 见下方「自定义格式」 |

```bash
# 导出全部论文（APA 风格，默认）
scholaraio export markdown --all

# 指定引用格式
scholaraio export markdown --all --style vancouver
scholaraio export markdown --all --style chicago-author-date
scholaraio export markdown --all --style jcp        # 自定义格式

# 导出到文件
scholaraio export markdown --all --style apa -o workspace/references.md

# 无序列表
scholaraio export markdown --all --bullet

# 按年份筛选
scholaraio export markdown --all --year 2020-2024 -o workspace/recent_refs.md
```

### 查看可用格式

```bash
scholaraio style list           # 列出全部格式（内置 + 自定义）
scholaraio style show jcp       # 查看某个自定义格式的代码
```

---

## 自定义期刊引用格式（Agent 精确控制）

### 原理

自定义格式以 Python 文件存储在 `data/citation_styles/<name>.py`，必须实现一个函数：

```python
def format_ref(meta: dict, idx: int | None = None) -> str:
    """
    meta 字段：title, authors (list), year, journal, volume, issue,
               pages, doi, publisher, paper_type, ...
    idx:  有序列表的编号（None = 无序/bullet）
    返回：格式化后的 Markdown 引用字符串
    """
```

### Agent 工作流：为指定期刊生成格式

当用户说「导出成 JCP 格式」「帮我按 Physical Review Letters 格式导出」：

1. **检查是否已有缓存**
   ```bash
   scholaraio style list
   ```
   如果已有 `jcp` 或目标格式名，直接跳到第 4 步。

2. **获取期刊官方格式说明**
   - 搜索：`<journal name> citation style guide` 或 `<journal name> reference format`
   - 或从 CSL 仓库获取标准定义：
     `https://raw.githubusercontent.com/citation-style-language/styles/master/<slug>.csl`
   - CSL 搜索：`https://github.com/citation-style-language/styles/`（支持 10,000+ 期刊）

3. **写 Python 格式化函数并保存**
   - 根据格式说明写 `format_ref(meta, idx)` 函数
   - 保存到 `data/citation_styles/<name>.py`
   - 可同时保存 `data/citation_styles/<name>.json`（记录来源和示例）

4. **导出**
   ```bash
   scholaraio export markdown --all --style <name> -o workspace/refs.md
   ```

### 示例：JCP 格式文件（data/citation_styles/jcp.py）

```python
# Journal of Chemical Physics / AIP Publishing 编号格式
# 来源：https://publishing.aip.org/wp-content/uploads/2021/05/JCP_Style_Guide.pdf

def format_ref(meta: dict, idx: int | None = None) -> str:
    authors = meta.get("authors") or []

    def _fmt(name):
        parts = name.split(",", 1)
        if len(parts) == 2:
            last, first = parts[0].strip(), parts[1].strip()
            initials = " ".join(f"{w[0]}." for w in first.split() if w)
            return f"{initials} {last}"
        return name

    if len(authors) == 1:
        author_str = _fmt(authors[0])
    elif len(authors) <= 3:
        fmt = [_fmt(a) for a in authors]
        author_str = ", ".join(fmt[:-1]) + f", and {fmt[-1]}"
    elif authors:
        author_str = _fmt(authors[0]) + " et al."
    else:
        author_str = "Unknown"

    title   = meta.get("title") or "Untitled"
    journal = meta.get("journal") or ""
    volume  = meta.get("volume") or ""
    pages   = meta.get("pages") or ""
    year    = meta.get("year") or "n.d."
    doi     = meta.get("doi") or ""
    start_page = pages.split("-")[0].strip() if pages else ""

    ref = f'{author_str}, "{title},"'
    if journal: ref += f" *{journal}*"
    if volume:  ref += f" **{volume}**,"
    if start_page: ref += f" {start_page}"
    ref += f" ({year})."
    if doi: ref += f" doi:{doi}"

    prefix = f"{idx}. " if idx is not None else "- "
    return prefix + ref
```

输出示例：
```
1. A. Vaswani et al., "Attention Is All You Need," *Advances in Neural Information Processing Systems* **30**, 5998 (2017). doi:10.48550/arXiv.1706.03762
```

---

## DOCX 导出（任意 Markdown → Word）

```bash
# 将 Markdown 文件导出为 Word
scholaraio export docx --input workspace/literature_review.md --output workspace/review.docx

# 添加文档标题
scholaraio export docx --input workspace/report.md --output workspace/report.docx --title "研究报告"

# 从 stdin 读取（配合 Claude 生成内容直接导出）
echo "# 标题\n内容..." | scholaraio export docx --output workspace/doc.docx
```

支持的 Markdown 元素：标题（H1-H9）、段落、**粗体**、*斜体*、列表、表格、代码块、引用块

**依赖**：需安装 `pip install python-docx`

> **高级排版**：`export docx` 仅做简单 Markdown → Word 转换。需要自定义样式、嵌入图片、表格等高级排版时，请使用 `/document` skill（直接调用 python-docx API）。

---

## 示例

用户说："把我所有论文导出成 BibTeX"
→ 执行 `export bibtex --all`

用户说："导出成 RIS，我要导入 Zotero"
→ 执行 `export ris --all -o workspace/library.ris`

用户说："给我一份 Markdown 格式的参考文献列表"
→ 执行 `export markdown --all`

用户说："按 Vancouver 格式导出文献列表"
→ 执行 `export markdown --all --style vancouver`

用户说："按 JCP 格式导出，我要投 Journal of Chemical Physics"
→ 先 `style list` 检查，若无则获取 JCP 格式说明、写 `data/citation_styles/jcp.py`，再 `export markdown --all --style jcp`

用户说："把这篇文献综述导出成 Word 文件"
→ 执行 `export docx --input workspace/review.md --output workspace/review.docx`

用户说："导出 DNS 相关的论文引用"
→ 先用 `usearch "DNS"` 搜索，再用结果中的目录名 / DOI / UUID 执行 `export markdown <标识1> <标识2> ...`

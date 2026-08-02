---
name: ingest
description: Use when the user wants to process new papers, patents, theses, documents, or proceedings from inbox into the knowledge base via the ingest pipeline. For rebuilding search indexes without ingesting inbox items, see the /index skill.
version: 1.0.0
author: wszqkzqk/scrinium
license: MIT
tags: ["academic", "papers", "patent", "pipeline", "pdf", "docx", "office"]
---
# 入库文档

将 inbox 中的 PDF、Office 文档（DOCX/XLSX/PPTX）或 Markdown 文件处理入库。支持论文、专利、学位论文、一般文档和论文集（proceedings）。

## 支持的文件格式

| 格式 | 放入目录 | 处理方式 |
|------|----------|----------|
| `.pdf` | `data/inbox/` 或 `data/inbox-doc/` | MinerU 转 Markdown |
| `.pdf` / `.md` | `data/inbox-patent/` | 专利文献（按公开号去重） |
| `.pdf` / `.md` | `data/inbox-proceedings/` | 论文集准备流程（先生成 `proceeding.md` + `split_candidates.json`） |
| `.docx` `.xlsx` `.pptx` | `data/inbox-doc/` | MarkItDown 转 Markdown |
| `.md` | 任意 inbox | 直接入库（跳过转换） |

## 执行逻辑

1. 根据用户意图选择预设：
   - **入库新文档**（默认）：使用 `ingest` 预设（= mineru, extract, dedup, ingest, embed, index）
   - **完整处理**：使用 `full` 预设（= mineru, extract, dedup, ingest, toc, l3, embed, index）
   - **仅重建索引**：使用 `reindex` 预设（= embed, index）
   - **仅内容富化**：使用 `enrich` 预设（= toc, l3, embed, index）

   > **注意**：`inbox-doc/` 始终使用专用步骤 `office_convert, mineru, extract_doc, ingest`，不受 preset 影响。`inbox-patent/` 和 `inbox-thesis/` 也有各自的固定流程。preset 中的 papers 级步骤（toc, l3）和 global 级步骤（embed, index）在处理完所有 inbox 后统一执行。
   >
   > **路由**：只需要重建索引、不涉及 inbox 摄入时，转交 `/index` skill（`index` / `embed` 命令，与 `pipeline reindex` 等价）。

2. 执行流水线命令：

```bash
scrinium pipeline <preset> [--dry-run] [--no-api] [--force] [--inspect]
```

可用预设：`full` | `ingest` | `enrich` | `reindex`

常用选项：
- `--dry-run` — 预览处理，不写文件
- `--no-api` — 离线模式，跳过外部 API 查询
- `--force` — 强制重新处理（toc/l3 等步骤）
- `--inspect` — 展示处理详情
- `--steps STEPS` — 自定义步骤序列（逗号分隔），如 `--steps toc,l3,index`
- `--list` — 列出所有可用步骤和预设

3. pipeline 依次处理五个 inbox 目录：
   - `data/inbox/` — 普通论文（有 DOI 才入库；无 DOI 时依次检测 thesis / book / arXiv 预印本，命中即入库，否则转 pending）
   - `data/inbox-thesis/` — 学位论文（跳过 DOI 去重，自动标记 thesis）
   - `data/inbox-patent/` — 专利文献（按公开号去重，自动标记 patent，跳过 DOI 去重）
   - `data/inbox-doc/` — 非论文文档（技术报告、讲义、Word/Excel/PPT、标准文档等，跳过 DOI 去重，LLM 生成标题/摘要）
   - `data/inbox-proceedings/` — 论文集（强制按 proceedings 处理；普通 `data/inbox/` 不做 proceedings 自动识别）

4. 论文类的 Stage-1 元数据提取由 `ingest.extractor` 控制：
   - `regex`：纯正则，最快，不调用 LLM
   - `auto`：正则优先，关键字段缺失时再调用 LLM
   - `robust`：正则 + LLM 双跑，校正 OCR 错误并处理多 DOI 情况（默认）
   - `llm`：纯 LLM 提取
   - 如果用户问“为什么标题 / 作者 / DOI 提取不准”，先检查这里的模式配置

5. 论文集（proceedings）采用半自动两阶段流程：
   - 第一阶段：`scrinium pipeline ingest` 只负责把 PDF/MD 转成 `data/proceedings/<Volume>/proceeding.md`，并生成 `split_candidates.json`
   - 此时不会自动拆成子论文；CLI 会显式提示等待 agent 审阅 `split_candidates.json` 并生成 `split_plan.json`
   - 第二阶段：由 agent/人工审阅结构后，执行

```bash
scrinium proceedings apply-split <proceeding_dir> <split_plan.json>
```

   - 这一步才会真正把子论文落到 `data/proceedings/<Volume>/papers/<Paper>/`

6. proceedings 拆分后支持半自动清洗流程：
   - 先执行

```bash
scrinium proceedings build-clean-candidates <proceeding_dir>
```

   - 该命令会生成 `clean_candidates.json`，用于汇总每个 child paper 的开头窗口、heading、缺失字段和结构信号
   - 然后由 agent/人工审阅并生成 `clean_plan.json`
   - 最后执行

```bash
scrinium proceedings apply-clean <proceeding_dir> <clean_plan.json>
```

   - 第一版支持的清洗动作是 `keep` / `rename` / `reclassify` / `drop`
   - agent 在这一步还可以顺手删除明显不合理的标签行，例如假 `# Comment 2.`、假 `# Reporter ...`
   - 这里的“删除标签”只针对明显错误的独立 heading/tag 行，不改正文段落内容
   - 推荐先做结构性清洗（保留/重命名/重分类/删除），再考虑作者、摘要、DOI 等元数据提纯

7. Office 文件处理流程（`data/inbox-doc/` 中的 DOCX/XLSX/PPTX）：
   - `step_office_convert`（MarkItDown）→ 转换为 `<stem>.md`
   - `step_extract_doc`（LLM 生成标题/摘要）
   - `step_ingest`（写入 `data/papers/`）
   - **依赖**：需安装 `pip install 'markitdown[docx,pptx,xlsx]'`

8. 专利文献处理逻辑（`data/inbox-patent/`）：
   - 自动提取公开号（CN/US/EP/WO/JP/KR/DE/FR/GB/TW/IN/AU 等格式）
   - 按公开号去重（非 DOI），跳过 DOI 检查
   - 自动标记 `paper_type: patent`

9. 无 DOI 论文的处理逻辑：
   - 来自 `data/inbox-thesis/` → 直接标记为 thesis 并入库
   - 来自 `data/inbox-doc/` → 标记为 document 类型，LLM 生成标题和摘要后入库
   - 来自 `data/inbox/` → 依次检测 thesis、book、arXiv 预印本
     - LLM 判断是 thesis → 标记并入库
     - LLM 判断是 book → 标记并入库
     - 提取到 arXiv ID → 标记为 preprint 并入库
     - 三者都不是 → 转入 `data/pending/` 待人工确认

10. 待确认项查看：ingest 结束后若有 pending / duplicate 条目，运行 `scrinium pending` 查看清单（按 issue 分组，含标题、duplicate_of 和处理建议）。处理 pending 是 ingest 工作流的一部分——入库操作后应主动检查一次。

11. 超长 PDF 会在 MinerU 转换前按需自动切分后合并：
   - 本地 MinerU 按 `chunk_page_limit`（默认 >100 页）
   - 云端 MinerU 同时遵循 `>600 页` 和 `>200MB` 两个限制，并在仅超大小时估算更安全的分片页数

12. 如果 `config.translate.auto_translate: true`，只要本次 pipeline 包含 inbox 步骤并成功入库新论文，系统会在 papers 阶段自动插入 `translate`，位置在 `embed/index` 之前：
   - 只翻译本次新入库论文，不会顺手重翻整个库
   - 目标语言读取 `translate.target_lang`
   - 这是配置驱动行为，不需要额外改 preset

## 示例

用户说："我放了几篇新论文到 inbox，帮我入库"
→ 执行 `pipeline ingest`

用户说："把新论文全部处理完，包括提取目录和结论"
→ 执行 `pipeline full`

用户说："我有几份技术报告放在 inbox-doc 里了"
→ 执行 `pipeline ingest`（pipeline 自动处理五个 inbox 目录）

用户说："我把一个 Word 文档放进 inbox-doc 了"
→ 执行 `pipeline ingest`（自动用 MarkItDown 转换 DOCX）

用户说："我有几篇专利放在 inbox-patent 了"
→ 执行 `pipeline ingest`（自动处理五个 inbox 目录，专利按公开号去重）

用户说："我有一本文集放在 inbox-proceedings 里"
→ 先执行 `pipeline ingest`，等生成 `split_candidates.json` 后由 agent 审阅，再执行 `scrinium proceedings apply-split ...`

用户说："重新建索引"
→ 执行 `pipeline reindex`

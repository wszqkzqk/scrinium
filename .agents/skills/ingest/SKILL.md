---
name: ingest
description: Use when the user wants to process new papers, patents, theses, documents, or proceedings from inbox into the knowledge base via the ingest pipeline, or to resolve pending items held for review. For rebuilding search indexes without ingesting inbox items, see the /index skill.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "papers", "patent", "pipeline", "pdf", "docx", "office"]
---
# 入库文档

将 inbox 中的 PDF、Office 文档（DOCX/XLSX/PPTX）或 Markdown 文件处理入库。支持论文、专利、学位论文、一般文档和论文集（proceedings）。

**框架边界**：元数据提取只有**纯正则**一条路径（`RegexExtractor`），框架内无任何 LLM 调用。规则失败或低置信时框架会输出 **`hint: ` 前缀的交接提示**——见到 hint 即由 agent 按本 skill 的工作流接管（读原文判定、修元数据），不要让用户手工处理。

## 支持的文件格式

| 格式 | 放入目录 | 处理方式 |
|------|----------|----------|
| `.pdf` | `data/inbox/` 或 `data/inbox-doc/` | MinerU 转 Markdown |
| `.pdf` / `.md` | `data/inbox-patent/` | 专利文献（按公开号去重） |
| `.pdf` / `.md` | `data/inbox-thesis/` | 学位论文直接入库通道（跳过 DOI 去重） |
| `.pdf` / `.md` | `data/inbox-proceedings/` | 论文集准备流程（先生成 `proceeding.md` + `split_candidates.json`） |
| `.docx` `.xlsx` `.pptx` | `data/inbox-doc/` | MarkItDown 转 Markdown |
| `.md` | 任意 inbox | 直接入库（跳过转换） |

## 执行逻辑

1. 根据用户意图选择预设：
   - **入库新文档**（默认）：使用 `ingest` 预设（= mineru, extract, dedup, ingest, index）
   - **完整处理**：`full` 与 `ingest` 等价（= mineru, extract, dedup, ingest, index）
   - **仅重建索引**：使用 `reindex` 预设（= index）
   - **仅内容富化**：使用 `enrich` 预设（= abstract, toc，均为纯规则步骤）

   > **注意**：`inbox-doc/` 始终使用专用步骤 `office_convert, mineru, extract_doc, ingest`（extract_doc 为纯规则），不受 preset 影响。`inbox-patent/` 和 `inbox-thesis/` 也有各自的固定流程。preset 中的 papers 级步骤（abstract, toc）和 global 级步骤（index）在处理完所有 inbox 后统一执行。
   >
   > **路由**：只需要重建索引、不涉及 inbox 摄入时，转交 `/index` skill（`scrinium index`，与 `pipeline reindex` 等价）。

2. 执行流水线命令：

```bash
scrinium ingest [--dry-run] [--no-api] [--force]
```

`scrinium ingest` 是 `scrinium pipeline ingest` 的直名别名（无参数时等价，且支持 pipeline 的全部选项）。需要其他预设时用完整形式：

```bash
scrinium pipeline <preset> [--dry-run] [--no-api] [--force]
```

可用预设：`full` | `ingest` | `enrich` | `reindex`

常用选项：
- `--dry-run` — 预览处理，不写文件
- `--no-api` — 离线模式，跳过外部 API 查询
- `--force` — 强制重新处理（toc 等步骤）
- `--steps STEPS` — 自定义步骤序列（逗号分隔），如 `--steps toc,index`
- `--list` — 列出所有可用步骤和预设

3. pipeline 依次处理五个 inbox 目录：
   - `data/inbox/` — 普通论文（有 DOI 才入库；无 DOI 时用标题启发式检测 thesis / book / arXiv 预印本，命中即入库，否则转 pending）
   - `data/inbox-thesis/` — 学位论文（跳过 DOI 去重，自动标记 thesis，直接入库）
   - `data/inbox-patent/` — 专利文献（按公开号去重，自动标记 patent，跳过 DOI 去重）
   - `data/inbox-doc/` — 非论文文档（技术报告、讲义、Word/Excel/PPT、标准文档等，跳过 DOI 去重；以首标题/文件名 + 前 500 词做最小元数据入库，正式标题/摘要由 agent 后处理直写）
   - `data/inbox-proceedings/` — 论文集（强制按 proceedings 处理；普通 `data/inbox/` 不做 proceedings 自动识别）

4. 元数据提取为纯正则（`RegexExtractor`）。提取低置信（缺 title/authors）的论文会在输出中附 hint：`建议派 subagent 读原文核对后用 scrinium repair 修正`——见到即按下面的"低置信修复"接管。

5. 论文集（proceedings）采用半自动两阶段流程：
   - 第一阶段：`scrinium ingest` 只负责把 PDF/MD 转成 `data/proceedings/<Volume>/proceeding.md`，并生成 `split_candidates.json`
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
   - `step_extract_doc`（纯规则：首标题/文件名 + 前 500 词做最小元数据）
   - `step_ingest`（写入 `data/papers/`）
   - **依赖**：需安装 `pip install 'markitdown[docx,pptx,xlsx]'`
   - 入库后由 agent 后处理：读文档内容，直写 meta.json 的正式 `title`/`abstract`，然后 `scrinium index` 生效

8. 专利文献处理逻辑（`data/inbox-patent/`）：
   - 自动提取公开号（CN/US/EP/WO/JP/KR/DE/FR/GB/TW/IN/AU 等格式）
   - 按公开号去重（非 DOI），跳过 DOI 检查
   - 自动标记 `paper_type: patent`

9. 无 DOI 论文的处理逻辑（`data/inbox/`）：
   - 标题启发式命中 thesis → 标记并入库
   - 标题启发式命中 book → 标记并入库
   - 提取到 arXiv ID → 标记为 preprint 并入库
   - 都不命中 → 转入 `data/pending/` 并附 hint，走下面的 pending 解决工作流
   - 已知是学位论文的 PDF 应直接放 `data/inbox-thesis/`（跳过 DOI 去重的直接入库通道）

10. 待确认项查看：ingest 结束后若有 pending / duplicate 条目，运行 `scrinium pending` 查看清单（按 issue 分组，含标题、duplicate_of 和每条的处理建议 hint）。处理 pending 是 ingest 工作流的一部分——入库操作后应主动检查一次。

11. 超长 PDF 会在 MinerU 转换前按需自动切分后合并：
   - 本地 MinerU 按 `chunk_page_limit`（默认 >100 页）
   - 云端 MinerU 同时遵循 `>600 页` 和 `>200MB` 两个限制，并在仅超大小时估算更安全的分片页数

## Pending 解决工作流（agent 接管）

`data/pending/<stem>/` 里有原始 PDF、`paper.md` 和 `pending.json`（含 issue、已提取元数据和 hint）。逐条处理：

1. `scrinium pending` 列出全部待确认项（按 issue 分组，每条带 hint）
2. **每条派一个 subagent 读原文判定**（多条并行，互不重叠）：
   - 读 `data/pending/<stem>/paper.md`（必要时看 PDF），判定真实类型：普通论文 / thesis / book / 专利 / 真缺 DOI 的会议报告等
   - 核对并补全元数据（标题、作者、年份、DOI——可从原文、Google Scholar 思路或 Crossref 查询获得）
3. 按判定结果分路处理：
   - **thesis** → 把源 PDF 移入 `data/inbox-thesis/`，重跑 `scrinium ingest`（该通道跳过 DOI 去重直接入库）
   - **专利** → 移入 `data/inbox-patent/` 重跑
   - **普通论文（已找到 DOI）** → 放回 `data/inbox/` 重跑 `scrinium ingest`；或直接 `scrinium repair <pending-stem> --title "..." --doi "..." [--author ...] [--year ...]`——repair 直接支持 pending 项：带查重护栏（DOI/arXiv ID 命中库内已有论文则拒绝入库），通过后移入 `data/papers/`、自动清除 pending 目录，然后 `scrinium index`
   - **确认为非论文文档** → 移入 `data/inbox-doc/` 重跑
   - **duplicate** → subagent 对比两篇后决定去留：保留一篇，删除另一篇目录（或确认是不同版本均保留并说明理由）
4. 处理成功后删除对应的 `data/pending/<stem>/` 目录（repair 路径会自动移除），重跑 `scrinium pending` 确认清零
5. 闭环后跑一次 `scrinium index`

## 低置信修复（入库后）

对入库时标记低置信（缺 title/authors，输出带 hint）的论文：

1. subagent 读 `data/papers/<stem>/paper.md` 核对真实元数据
2. `scrinium repair "<stem>" --title "正确标题" [--author "一作"] [--year YYYY] [--doi "10.xxx/..."]`（先 `--dry-run` 预览）
3. `scrinium index` 重建索引

## 入库后建议

批量入库完成后，建议运行一次 `scrinium audit` 做元数据审查（见 `/audit` skill），把漏网的质量问题（缺摘要、标题不一致、未打标等）一并接管处理。

## 示例

用户说："我放了几篇新论文到 inbox，帮我入库"
→ 执行 `scrinium ingest`；结束后跑 `scrinium pending` 检查滞留项，有则按 pending 工作流接管；最后建议 `scrinium audit`

用户说："把新论文全部处理完，包括提取目录"
→ 执行 `pipeline full`，再执行 `pipeline enrich`

用户说："我有几份技术报告放在 inbox-doc 里了"
→ 执行 `scrinium ingest`（自动处理五个 inbox 目录）；文档入库后 agent 后处理直写正式标题/摘要

用户说："我把一个 Word 文档放进 inbox-doc 了"
→ 执行 `scrinium ingest`（自动用 MarkItDown 转换 DOCX）

用户说："我有几篇专利放在 inbox-patent 了"
→ 执行 `scrinium ingest`（自动处理五个 inbox 目录，专利按公开号去重）

用户说："这是我下载的几篇博士学位论文 PDF"
→ 放入 `data/inbox-thesis/` 后执行 `scrinium ingest`（跳过 DOI 去重直接入库）

用户说："我有一本文集放在 inbox-proceedings 里"
→ 先执行 `scrinium ingest`，等生成 `split_candidates.json` 后由 agent 审阅，再执行 `scrinium proceedings apply-split ...`

用户说："清理一下 pending 里的滞留论文"
→ 执行 `scrinium pending`，逐条派 subagent 读原文判定 → repair / 移入对应 inbox 重跑，清零后 `scrinium index`

用户说："重新建索引"
→ 执行 `pipeline reindex`（或 `scrinium index`，见 `/index` skill）

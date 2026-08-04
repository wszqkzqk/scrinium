---
name: audit
description: Audit paper data quality in the knowledge base and take over repairs. Rule-based checks surface missing fields, filename issues, DOI duplicates, and title mismatches with per-issue fix hints; agent/subagents then verify against the original text and fix meta.json directly. Use when the user wants to check data quality, find problems, or fix metadata issues.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "research", "metadata", "data-quality"]
---
# 论文审计

检查已入库论文的数据质量，并**接管修复**——audit 不止于诊断：规则检查输出的每条问题都带修复建议（hint），agent 派 subagent 读原文核对后直接修改 meta.json 闭环。

## 阶段一：规则化检查

```bash
scrinium audit [--severity error|warning|info]
```

问题按严重程度分类，每条附 `hint: ` 修复建议：
- **错误**：缺少标题、缺少 MD 文件、JSON 解析失败、DOI 重复
- **警告**：缺少 DOI/摘要/年份/作者/期刊、MD 过短、标题不一致、文件名年份不匹配
- **提示**：文件名不符合规范格式

## 阶段二：subagent 核对（agent 深度诊断）

对需要理解才能判定的问题（`title_mismatch`、可疑元数据、DOI 重复），派 subagent 逐篇核对（多篇并行、互不重叠）。每个 subagent：

1. 用 Read 工具读取 `data/papers/<paper>/meta.json` 和 `paper.md`（前 80 行起，必要时读更多）
2. 判断 MD 正文的实际主题/标题/作者/年份是否与 JSON 元数据一致
3. 区分无害差异（MinerU H1 识别问题）vs 真正的内容错配
4. 带回「判定 + 正确元数据」的 T1 结论

## 阶段三：修复

按问题性质分两条路径：

**agent 直改 meta.json**（推荐，大多数问题）：
- 用 Edit 工具直接修正 `data/papers/<paper>/meta.json` 的 `title`/`authors`/`year`/`journal`/`abstract` 等字段
- 适用：标题/作者/年份/期刊错配、摘要缺失或截断（读原文直写 `abstract`）、 harmless H1 误判后的标题归一

**`repair` 命令**（需要 API 补全或目录重命名时）：

```bash
# 先 dry-run 预览
scrinium repair "<paper-id>" --title "正确标题" [--author "一作"] [--year YYYY] [--doi "10.xxx/..."] --dry-run

# 确认后执行（会查 API 补全元数据、重写 meta.json 并规范化目录名）
scrinium repair "<paper-id>" --title "正确标题" [--author "一作"] [--year YYYY] [--doi "10.xxx/..."] [--no-api]
```

**修复后统一重建索引**：

```bash
scrinium index
```

目录名不规范的批量问题转交 `/rename` skill；DOI 重复参照 pending 工作流由 subagent 对比两篇后决定去留（见 `/ingest` skill）。

## 检查规则

| 规则 | 级别 | 说明 |
|------|------|------|
| `missing_title` | error | 缺少标题 |
| `missing_md` | error | JSON 无对应 MD 文件 |
| `duplicate_doi` | error | DOI 重复 |
| `missing_doi` | warning | 缺少 DOI |
| `missing_abstract` | warning | 缺少摘要 |
| `title_mismatch` | warning | JSON 标题与 MD H1 不一致 |
| `nonstandard_filename` | info | 文件名不符合规范格式 |
| `untagged` | info | 未打策展标签（可用 `/curate` 流程或 `scrinium tag` 补充） |

## 示例

用户说："帮我检查一下论文库有没有问题"
→ 执行阶段一规则化检查，按 hint 汇总问题清单

用户说："深度检查并修掉"
→ 完整闭环：阶段一 → 派 subagent 逐篇核对 title_mismatch 等可疑项 → 直改 meta.json / `repair` → `scrinium index` → 重跑 `audit` 确认不再复现

用户说："修复那些错配的论文"
→ 执行阶段二 + 阶段三

## 完成前检查

- **笔记写了吗**：subagent 核对确认的真实内容错配（非无害 H1 问题），已通过 CLI 写入对应论文的笔记：
  ```bash
  scrinium show "<paper-id>" --append-notes "## YYYY-MM-DD | <任务来源> | audit
  - 关键发现"
  ```
- **修复闭环了吗**：确认的错配都已直改 meta.json 或 `repair`，并执行 `scrinium index`，重跑 `audit` 不再复现相同问题
- **输出在 workspace 吗**：批量诊断结果和修复清单已保存到 `workspace/` 下

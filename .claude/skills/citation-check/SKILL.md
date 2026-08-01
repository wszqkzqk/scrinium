---
name: citation-check
description: Verify citations in AI-generated or human-written text against the local knowledge base. Catches hallucinated references, wrong metadata, and missing papers. Use when the user wants to check if citations are real and accurate.
version: 1.1.0
author: ZimoLiao/scholaraio
license: MIT
tags: ["academic", "citations", "verification", "hallucination"]
---
# 引用验证

检查文本中的引用是否真实、准确，防止 AI 幻觉引用和元数据错误。

**重要背景**：AI 生成的学术文本中，引用有相当比例是幻觉或错配（编造的论文、张冠李戴、元数据拼凑）。即使是人类写的文本也常有年份/期刊名错误。本 skill 的目标是在投稿前消灭所有引用问题。

## CLI 命令（首选方法）

```bash
# 检查文件中的引用
scholaraio citation-check <file>

# 在工作区范围内验证
scholaraio citation-check <file> --ws <workspace-name>

# 从 stdin 读取
cat draft.md | scholaraio citation-check
```

CLI 自动提取 author-year 格式的引用（`Author (Year)`、`(Author, Year)`、`Author & Author (Year)`、`Author et al. (Year)` 等），在本地知识库中搜索匹配，输出每条引用的验证状态：

| 状态 | 含义 |
|------|------|
| **VERIFIED** | 本地库有唯一匹配，作者+年份一致 |
| **AMBIGUOUS** | 本地库有多条匹配，需人工确认 |
| **NOT_IN_LIBRARY** | 本地库中无此论文 |

对于 AMBIGUOUS 和 NOT_IN_LIBRARY 的结果，可进一步执行手动深度验证（见下文）。

## 前提

用户提供待检查的文本（粘贴、文件路径、或指定 workspace 中的草稿文件）。
如有 workspace，优先在工作区范围内验证。

## 手动深度验证

CLI 完成初步筛查后，对问题引用执行更细致的检查：

### Layer 1 — 本地库匹配

```bash
scholaraio search-author "<Author>" --top 5
scholaraio usearch "<关键词 from title>" --top 5
```
在本地库中找到匹配论文后，核对：作者名、年份、标题、期刊是否一致。

### Layer 2 — DOI/元数据核验

如果本地库有匹配，读取 meta.json 中的 DOI 和详细元数据交叉比对。
如果本地库无匹配，提醒用户——该引用不在工作区/知识库中。

### Layer 3 — 内容一致性

对于关键引用（支撑核心论点的），加载 L2-L3 检查：
```bash
scholaraio show <paper-id> --layer 3
```
验证：文本中对该论文的描述是否与论文实际内容一致？是否存在过度解读或断章取义？

## 常见问题模式

- **AI 幻觉引用**：作者名和年份拼凑出一篇不存在的论文——标记 SUSPICIOUS
- **张冠李戴**：引用了真实论文但描述的是另一篇的内容——标记 CONTENT MISMATCH
- **元数据错误**：年份差一年、期刊名拼错、一作搞错——标记 METADATA MISMATCH 并给出正确值
- **过度引用**：一个论点堆了 5+ 引用但大部分并不直接相关——建议精简

## 示例

用户说："帮我检查这段文字里的引用是否正确"
→ 先运行 `scholaraio citation-check <file>`，再对问题引用逐条深入验证

用户说："检查 workspace/my-paper/introduction.md 里的引用"
→ 运行 `scholaraio citation-check workspace/my-paper/introduction.md --ws my-paper`

## 完成前检查

- **笔记写了吗**：对做过 Layer 3 内容一致性核验的论文，关键发现已通过 CLI 写入笔记：
  ```bash
  scholaraio show "<paper-id>" --append-notes "## YYYY-MM-DD | <workspace> | citation-check
  - 关键发现"
  ```
- **引用查了吗**：所有 AMBIGUOUS / NOT_IN_LIBRARY 的引用都已逐条处理，没有未经核验就放行的
- **输出在 workspace 吗**：验证结论和修订建议已写入 `workspace/<name>/` 下的文件，而不只停留在对话里

---
name: translate
description: Translate a paper's markdown to a target language (default Chinese) via agent/subagent chunked translation. Preserves LaTeX formulas, code blocks, and images; supports resume from partial output and batch translation. Use when the user wants to read papers in their native language or translate non-Chinese documents.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "papers", "translation", "multilingual"]
---
# 论文翻译（agent 接管工作流）

将论文 Markdown 翻译为目标语言（默认中文）。框架不再内置翻译命令——翻译由 agent 编排 subagent 完成：真读全文、携带术语表、分块翻译，质量高于一次性 LLM 调用。译文保存为论文目录内的 `paper_{lang}.md`（`lang` 为 ISO 639-1 代码，如 `zh`/`en`/`ja`），原文保持不变。

**存储约定（框架保留的原语）：**
- 译文文件：`data/papers/<Author-Year-Title>/paper_{lang}.md`
- 元数据：`meta.json` 的 `translations` 字段记录各语言译文状态
- 读取译文：`scrinium show "<paper-id>" --layer 4 --lang zh`

## 单篇翻译工作流

### 1. 读取与切分

```bash
scrinium show "<paper-id>" --layer 4
```

读入全文后**按章节切分**（沿 Markdown 一级/二级标题边界），每块是一个自然的翻译单元。切分时保证：代码块、公式块、图片引用不跨块截断。

> 无章节标题的文体（letter、部分期刊格式）按段落块切分；**参考文献节（REFERENCES）不翻译**，译完后将原文该节原样追加到译文末尾。分块 subagent 只返回译文文本（只读型即可），主 agent 负责按顺序落盘。

### 2. 准备术语表

- 若同一领域已翻译过论文，先复用既有术语表（见"术语表复用"）
- 否则从全文扫出专业术语（方法名、体系名、专有名词），拟定 10-30 条「原文 → 译文」对照
- 术语表写入 `workspace/translation-ws/glossary-<领域>.md`，跨论文、跨会话复用

### 3. 并行 subagent 分块翻译

把各块派给并行 subagent 翻译。每个 subagent 的 prompt 必须包含：

```text
翻译以下论文章节为<目标语言>。要求：
1. 完整保留 LaTeX 公式（$...$/$$...$$）、代码块、图片引用（![](images/...)）、Markdown 结构
2. 人名、期刊名、模型/方法专名保持原文；首次出现的术语按术语表翻译
3. 术语表：<逐条粘贴 glossary>
4. 只返回译文 Markdown，不要任何解释

<章节原文>
```

subagent 只带回译文（T1）；主 agent 按原顺序**顺序追加**写入 `paper_{lang}.md`。

### 4. 断点续翻约定

- `paper_{lang}.md` 的部分文件本身就是断点：翻译中断后，从已有文件的章节边界继续，未译章节接着追加即可，**不要从头重翻**
- 续翻前先读已有 `paper_{lang}.md` 尾部，确认最后一个完整章节，从下一章继续
- 全文完成前，`meta.json.translations` 中该语言标记 `"status": "partial"`

### 5. 更新 meta.json

全部章节译完后，用 Edit 工具更新论文目录的 `meta.json`：

```json
"translations": {
  "zh": {
    "file": "paper_zh.md",
    "source_lang": "en",
    "translated_at": "2026-08-04T12:00:00",
    "translated_by": "agent"
  }
}
```

未译完时写 `"status": "partial"`，续翻完成后移除该键。

### 6. 抽查验证

```bash
scrinium show "<paper-id>" --layer 4 --lang zh
```

抽查 2-3 个章节：公式/图片/代码块是否保留、术语是否与术语表一致、有无漏译段落。

## 批量翻译

批量 = **多篇论文各派一个 subagent**（每篇内部按上面的单篇流程走），互不重叠并行派发。每个 subagent 自己完成读原文 → 分块 → 翻译 → 写 `paper_{lang}.md` → 更新 meta.json，只带回「完成/部分 + 章节数」的 T1 结论。所有 subagent 共用同一份领域术语表。

## 术语表复用

- 存放：`workspace/translation-ws/glossary-<领域>.md`（Markdown 表格：原文 | 译文 | 备注）
- 每次翻译前查一下是否已有相关领域术语表；翻译中遇到新术语随手补充
- 同 workspace 的系列论文共享一份，保证术语一致性

## 示例

用户说："把这篇英文论文翻译成中文"
→ 单篇流程：`show --layer 4` 读原文 → 按章节切分 → 准备/复用术语表 → 并行 subagent 翻译 → 顺序写 `paper_zh.md` → 更新 `meta.json.translations` → `show --layer 4 --lang zh` 抽查

用户说："把这个工作区的 5 篇论文都翻译成中文"
→ 批量流程：5 个 subagent 各负责一篇，共用术语表，并行派发

用户说："上次翻译到一半断了，继续翻"
→ 读已有 `paper_zh.md` 确认断点章节，从下一章继续翻译并追加；完成后去掉 meta.json 里的 `"status": "partial"`

用户说："看这篇论文的中文版"
→ 执行 `scrinium show "<paper-id>" --layer 4 --lang zh`；不存在则告知尚未翻译，询问是否启动翻译

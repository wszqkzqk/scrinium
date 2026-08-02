---
name: translate
description: Translate paper markdown to a target language (default Chinese). Preserves LaTeX formulas, code blocks, and images. Supports single paper or batch translation. Use when the user wants to read papers in their native language or translate non-Chinese documents.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "papers", "translation", "multilingual"]
---
# 论文翻译

将论文 Markdown 翻译为目标语言（默认中文），保留 LaTeX 公式、代码块、图片引用和 Markdown 格式。翻译结果保存为论文目录内的 `paper_{lang}.md`，原文保持不变；如需可携带分享，可额外导出到 `workspace/translation-ws/<Author-Year-Title>/`。

实现特性：
- 单篇翻译按 `config.translate.concurrency` 并发请求多个分块，并在终端显示块级进度
- 在论文目录下创建临时工作目录，按块写入 `parts/*.md`
- 网络抖动时对单块做超时重试与指数退避（默认最多 5 次尝试）
- 中途中断后可从临时工作目录续翻
- `--force` 清理旧的临时翻译目录并从头重新翻译
- `--portable` 额外生成 `workspace/translation-ws/<Author-Year-Title>/paper_{lang}.md` 和对应的 `images/`

## 配置

`config.yaml` 中可设置默认行为：

```yaml
translate:
  auto_translate: false   # 入库时是否自动翻译（默认关闭）
  target_lang: zh          # 目标语言（zh/en/ja/ko/de/fr/es）
  chunk_size: 4000         # 分块大小（字符数）
  concurrency: 20          # 总翻译并发预算（单篇时用于 chunk 并发，批量时会在论文间分摊）
```

每次调用时可通过 CLI 参数覆盖默认值。

## 执行逻辑

### 单篇翻译

```bash
scrinium translate "<paper-id>" [--lang zh] [--force] [--portable]
```

### 批量翻译

```bash
scrinium translate --all [--lang zh] [--force] [--portable]
```

### 查看翻译

```bash
scrinium show "<paper-id>" --layer 4 --lang zh
```

### 作为 pipeline 步骤

```bash
scrinium pipeline --steps toc,l3,translate
```

> **注意**：`translate` 默认不在预设（`full`/`ingest`/`enrich`/`reindex`）中；可通过 `--steps` 显式指定。若 `config.translate.auto_translate=true` 且 pipeline 包含 inbox 步骤，`translate` 会在 papers 阶段自动注入。

## 工作流程

1. 检测论文原文语言（基于字符集启发式检测）
2. 如果已是目标语言，跳过
3. 将 Markdown 按段落边界分块（保留代码块和公式完整性）
4. 通过 LLM 逐块翻译，保留所有格式标记
5. 单篇翻译会并发请求多个分块，但只按原顺序推进最终输出
6. 在论文目录下创建临时工作目录（如 `.translate_zh/`），将每块分别写入 `parts/*.md`
7. 状态写入 `state.json` / `chunks.json`；失败块会记录错误并在下次续翻时单独补跑
8. 每个分块带超时重试和指数退避
9. 若已有连续成功前缀，则同步刷新 `paper_{lang}.md`，方便中途查看已完成部分
10. 若指定 `--portable`，则额外复制一份到 `workspace/translation-ws/<Author-Year-Title>/`，并复制 `images/` 以保证脱离原目录后图片仍可用
11. 若前面某块失败但后面某些块已成功，这些成功块仍会保留在临时工作目录里；下次续翻时会跳过已成功块，只补失败或未完成的块
12. 全部完成后删除临时工作目录，并在 `meta.json` 中记录翻译元数据

## 进度与续翻

单篇翻译会输出：
- 总块数
- 当前块进度（如 `翻译进度: 3/12`）
- 中断位置
- 是否可续翻

如果中途中断：

```bash
scrinium translate "<paper-id>" --lang zh
```

会自动检测论文目录下的临时翻译工作目录（如 `.translate_zh/`），并从未完成或失败的块继续。

如果想忽略已有部分结果并重新开始：

```bash
scrinium translate "<paper-id>" --lang zh --force
```

会删除旧的临时翻译目录和旧的 `paper_zh.md`，从头重新翻译。

## 示例

用户说："把这篇英文论文翻译成中文"
-> 执行 `scrinium translate "<paper-id>" --lang zh`

用户说："把所有论文翻译成中文"
-> 执行 `scrinium translate --all --lang zh`

用户说："看这篇论文的中文版"
-> 执行 `scrinium show "<paper-id>" --layer 4 --lang zh`

用户说："重新翻译这篇论文"
-> 执行 `scrinium translate "<paper-id>" --force`

用户说："上次翻译到一半断了，继续翻"
-> 直接执行 `scrinium translate "<paper-id>" --lang zh`

用户说："给我一份可以单独发给别人的译文，别丢图"
-> 执行 `scrinium translate "<paper-id>" --lang zh --portable`

---
name: arxiv
description: Use when the user wants to browse arXiv preprints, search arXiv directly, fetch a PDF by arXiv ID or URL, or send a preprint straight into the ingest pipeline.
version: 1.0.0
author: wszqkzqk/scrinium
license: MIT
tags: ["academic", "papers", "arxiv", "preprint"]
---

# arXiv 预印本

当任务明确围绕 arXiv 这一预印本来源时，使用本 skill。

这是一个轻量的来源工作流 skill：

- `search` skill 负责整体的论文检索路由
- `arxiv` skill 负责预印本的发现、浏览、获取，以及可选的入库

## 何时使用

适用于用户想要：

- 浏览最近或特定分类的预印本
- "随便看看" arXiv 上某个方向最近有什么
- 直接检索 arXiv，而不是只搜本地库
- 通过 arXiv ID、`abs` URL 或 `pdf` URL 获取某篇论文
- 把预印本下载到 `data/inbox/`
- 把 arXiv 预印本直接送入 ingest 流水线

不适用于：

- 任务主要是检索本地知识库
- 用户想要完整的多来源文献调研；改用 `search` 或 `explore`

## 核心工作流

### 1. 判断是浏览/检索，还是获取/入库

- 如果用户想四处看看、发现预印本、或了解最新动态，先用 `arxiv search`
- 如果用户想结合本地库做跨来源检索，用 `fsearch --scope main,arxiv`
- 如果用户已经明确要某篇 arXiv 论文，用 `arxiv fetch`
- 如果目标是"现在就把这篇预印本放进我的库"，用 `arxiv fetch <id> --ingest`

### 2. 使用正确的命令

直接检索 arXiv：

```bash
scrinium arxiv search "<query>"
scrinium arxiv search "<query>" --category physics.flu-dyn
scrinium arxiv search --category cs.LG --sort recent
```

需要 arXiv 补充本地库时，用联邦搜索：

```bash
scrinium fsearch "<query>" --scope main,arxiv
scrinium fsearch "<query>" --scope arxiv
```

只下载 PDF：

```bash
scrinium arxiv fetch 2603.25200
scrinium arxiv fetch arXiv:2603.25200v1
scrinium arxiv fetch https://arxiv.org/abs/2603.25200v1
```

下载并立即入库：

```bash
scrinium arxiv fetch 2603.25200 --ingest
```

### 3. 保持来源语义清晰

- arXiv 是预印本来源，不是主精选知识库
- 用它快速发现新工作，或拉取指定预印本
- 如果论文与用户正在进行的工作相关，就入库，而不是反复把它当外部结果对待

## 实用经验

- 用户说"也搜一下 arXiv"时，优先 `fsearch --scope main,arxiv`
- 用户说"看看最近有什么预印本"时，优先 `arxiv search --sort recent`
- 用户给出 arXiv ID 或 URL 时，不要先做宽泛检索；直接 `arxiv fetch`
- 用户明显在为后续阅读或写作收集论文时，优先 `--ingest`

## 输出风格

- 明确区分哪些结果来自 arXiv、哪些来自本地库
- 使用联邦搜索时，区分本地命中与仅 arXiv 命中
- 只下载未入库时，提醒用户 PDF 现在位于 `data/inbox/`
- 下载并入库时，说明论文已进入正常 ingest 流程

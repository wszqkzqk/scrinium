---
name: workspace
description: Manage workspace paper subsets — create workspaces, add/remove papers, search within a workspace, and export BibTeX. Workspaces are thin layers that reference papers in the main library by UUID. Use when the user wants to organize papers into groups for writing, review, or focused analysis.
version: 1.0.0
author: ZimoLiao/scholaraio
license: MIT
tags: ["academic", "papers", "workspace", "organization"]
---
# 工作区管理

工作区是论文子集管理工具。每个工作区引用主库中的论文（通过 UUID），支持在子集内搜索和导出。

## 执行逻辑

### 创建工作区

```bash
scholaraio ws init <名称>
```

### 添加论文

工作区必须先存在：`ws add` 对不存在的名称会报错并列出现有工作区（需先 `ws init` 创建），`ws show` 同理。无法解析的论文标识会逐条报告在输出中。

逐个添加：
```bash
scholaraio ws add <名称> <论文标识...>
```

论文标识可以是：DOI、目录名、UUID。需要按关键词批量添加时，请使用 `--search`。

批量添加：
```bash
scholaraio ws add <名称> --search "<查询词>" [--top N] [--year YYYY] [--journal 期刊名] [--type 类型]
scholaraio ws add <名称> --topic <主题ID>
scholaraio ws add <名称> --all
```

- `--search`：按融合检索结果批量添加，支持 `--top`/`--year`/`--journal`/`--type` 过滤
- `--topic`：按 BERTopic 主题 ID 批量添加该主题下的全部论文
- `--all`：将主库全部论文加入工作区

三个批量参数互斥。提供批量参数时，位置参数 `<论文标识>` 被忽略。

### 移除论文

```bash
scholaraio ws remove <名称> <论文标识...>
```

### 列出所有工作区

```bash
scholaraio ws list
```

### 查看工作区论文

```bash
scholaraio ws show <名称>
```

### 重命名工作区

```bash
scholaraio ws rename <旧名称> <新名称>
```

### 在工作区内搜索

```bash
scholaraio ws search <名称> "<查询词>" [--top N] [--year YYYY] [--journal 期刊名] [--type 类型] [--mode unified|keyword|semantic]
```

搜索模式：
- `unified`（默认）：融合检索（关键词 + 语义 RRF 排序）
- `keyword`：FTS5 关键词检索
- `semantic`：FAISS 语义向量检索

范围限定在工作区论文内。

### 导出工作区 BibTeX

```bash
scholaraio ws export <名称> [-o 输出文件] [--year YYYY] [--journal 期刊名] [--type 类型]
```

## Context 管理

- 工作区论文较多时（>30 篇），`ws show` 的输出应由 subagent 执行并返回摘要（如"工作区包含 N 篇论文，涵盖 XX 方向"），避免直接输出长列表到主 context
- 论文全文（L4）应在 subagent 中阅读，仅将关键结论带回主 context
- 搜索结果超过 20 条时，优先用 subagent 处理并筛选

## 示例

用户说："帮我建一个 drag reduction 的工作区"
→ 执行 `ws init drag-reduction`

用户说："把这几篇论文加到工作区"
→ 执行 `ws add drag-reduction <DOI或目录名...>`

用户说："把搜索到的论文都加到工作区"
→ 执行 `ws add drag-reduction --search "turbulent drag reduction" --top 20`

用户说："把主题 3 的论文加到工作区"
→ 执行 `ws add drag-reduction --topic 3`

用户说："在工作区里搜 turbulent boundary layer"
→ 执行 `ws search drag-reduction "turbulent boundary layer"`

用户说："用关键词在工作区里搜"
→ 执行 `ws search drag-reduction "turbulent boundary layer" --mode keyword`

用户说："把工作区改个名"
→ 执行 `ws rename drag-reduction turbulence-control`

用户说："导出工作区的引用"
→ 执行 `ws export drag-reduction`

用户说："我有哪些工作区"
→ 执行 `ws list`

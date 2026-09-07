---
name: si
description: Discover, fetch, and attach Supporting Information (SI) for papers in the knowledge base. Use when the user wants to find SI for existing papers, attach a downloaded SI file, check SI coverage status, or handle si_orphan pending items.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["academic", "papers", "supporting-information", "supplementary", "pipeline"]
---
# SI（Supporting Information）获取与挂接

SI 不是独立的库条目，而是主论文的附件，存放在主论文目录的 `si/` 子目录中：

```
data/papers/<Author-Year-Title>/
├── meta.json        # "si" 字段：mentioned / files / fetch_status
├── paper.md
└── si/
    ├── <name>.pdf     # 原始文件（PDF/Excel/坐标文件等，原样保留）
    ├── <name>.md      # 转换文本（进 FTS 索引，随主论文一起可检索）
    └── images/        # SI 图表（Figure S1 等，可直接读图分析）
```

**信任模型：自动优先，失败抛给模型**。规则链只产出候选 URL；归属由 DOI 来源绑定的（URL 从 DOI 推导 / 文件经 DOI 匹配）跳过内容验证直接挂接；归属不明的（agent 手动挂接）必须过严格验证（SI 关键词 + 主文标题/作者命中）。任何失败写入 `fetch_status` 并输出 hint，由 agent 按本 skill 接管。

## 命令

```bash
scrinium si scan                    # 全库扫描，标记正文引用了 SI 的论文（写 si.mentioned）
scrinium si status                  # 队列总览：各状态计数 + 待接管清单
scrinium si fetch <paper-id>        # 自动获取单篇
scrinium si fetch --missing         # 批量获取（mentioned 且未挂接、非终态）
scrinium attach-si <paper-id> <file> [--source-url URL] [--no-convert] [--no-verify] [--dry-run]
scrinium show <paper-id> --si       # 查看 SI 转换文本
```

## fetch_status 含义与接管动作

| 状态 | 含义 | agent 动作 |
|---|---|---|
| `not_found` | 规则链无候选/候选均 404 | **最值得接管**：web search 找 SI |
| `blocked` | 出版社 403/429 | 换渠道：Europe PMC / 作者主页 / 预印本镜像 |
| `mismatch` | 下载件验证未过（仅严格模式） | 人工核对下载到的文件 |
| `paywalled` | SI 付费墙（少见） | 判断是否有 OA 镜像；没有则置 `exhausted` |
| `error` | 网络/转换错误 | 直接重试 `scrinium si fetch <paper-id>` |
| `exhausted` | 模型也找不到（终态） | 不再重试 |

## 标准工作流

1. `scrinium si scan` 刷新标记 → `scrinium si status` 看队列
2. `scrinium si fetch --missing` 自动批量获取（末尾有汇总和失败清单）
3. 对失败项（not_found/blocked/mismatch）**每篇派一个 subagent 并行接管**：

```text
为论文 "<paper-id>"（目录 data/papers/<dir>/）寻找 Supporting Information：
1. 先读 meta.json 拿到 title/doi，web search: "<title>" supporting information PDF
   （也可试 Europe PMC: europepmc.org 搜 DOI 查 supplementary files）
2. 下载到 /tmp 后运行: scrinium attach-si <paper-id> <file> --source-url <url>
   attach-si 会自动完成验证 → 转换 → 入库 → 索引；验证失败会告知原因
3. 若确认该文没有 SI（纯理论/综述，或出版社未提供），把 meta.json 的
   si.fetch_status 置为 "exhausted" 终止重试
4. 返回一句话结论（ok / exhausted / 原因）
```

4. 全部完成后 `scrinium si status` 确认队列收敛

## 入库时的 SI 自动路由（无需手动）

- inbox 中文件名疑似 SI 的条目（`*_si_001.pdf`、`mmc1.pdf`、`supporting-*.pdf` 等）会被延后处理：先等主文入库，再按 SI 文本中的 DOI 匹配挂接
- SI 带主文 DOI 且主文已在库 → 在 dedup 环节直接挂接，不按重复处理
- 未匹配到主文 → 转 `data/pending/` 的 `si_orphan`；之后主文入库时按 DOI 自动对账挂接
- 新论文入库后自动触发一次 SI 获取（配置 `ingest.si_fetch_on_ingest: false` 可关）

## si_orphan 待审项处理

`scrinium pending` 中 issue 为 `si_orphan` 的条目，派 subagent 读 `data/pending/<stem>/paper.md`：

- 确认主文且在库 → `scrinium attach-si <paper-id> data/pending/<stem>/<file>` 挂接，删除 pending 目录
- 主文未入库 → 把主文放入 inbox 入库（入库时自动对账挂接）
- 确认无对应主文（如下载错误的文件）→ 删除 pending 目录

## 注意

- SI 动辄上百页，批量 fetch 会消耗 MinerU 配额；`--no-convert` 只存原件不转换（不进索引）
- 规则链当前覆盖：ACS（Figshare）、RSC、Science、Elsevier、PLOS、Nature/Springer、Europe PMC（仅 OA 论文）；Wiley/AIP/bioRxiv 等未覆盖的直接进入 agent 接管队列
- 误挂排查：每个挂接记录都带 `source_url` 和 `attached_by`，`verify_note` 记录关键词/主文命中情况，可抽查

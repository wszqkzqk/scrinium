---
name: scientific-tool-onboarding
description: Use when adding or upgrading Scrinium support for a new scientific computing tool, especially when the work needs official docs ingestion, toolref integration, lightweight skill design, and end-to-end CLI verification
version: 1.0.0
author: wszqkzqk/scrinium
license: MIT
tags: ["scientific-computing", "toolref", "onboarding", "documentation"]
---

# 科学工具接入（Onboarding）

## 概述

把一个新科学工具接入 Scrinium，目标不是“写一份长教程”，而是形成这三个层次的闭环：

- `toolref` 能查官方接口和参数
- 对应 `skill` 能指导 agent 何时使用、如何验证
- CLI 在真实使用中足够稳，不只是测试能过

规范参考：

- 公开接入说明统一参照 [docs/guide/toolref-onboarding.md](../../../docs/guide/toolref-onboarding.md)
- 运行时行为统一参照 `scientific-runtime` skill

## 何时使用

适用于：
- 新增一个科学计算工具到 `scrinium toolref`
- 升级某个工具的官方文档源或版本策略
- 发现现有 scientific skill 过重，需要改成 `toolref-first`

不适用于：
- 只写一篇一次性笔记
- 只修一个小 typo

## 核心工作流

### 1. 先定“官方真源”

优先级：
- 官方文档站
- 官方源码仓库中的文档目录
- 官方维护的 README / man page / PDF

不要优先用：
- 博客
- 第三方教程
- 论坛帖子

要求：
- 记录文档 URL、版本策略、格式（RST / HTML / man / Markdown / PDF）
- 判断适合 `git` 抓取还是 `manifest` 抓取

经验判断：
- 如果官方文档天然按源码版本演进、结构稳定、页面很多，优先 `git`
- 如果官方文档是独立文档站、页面总数可控、但抓取噪音和网络波动明显，优先 `manifest`
- 不要为了“理论更完整”强行选 `git`；用户在乎的是 agent 能不能顺手查到
- 如果文档站有“总目录页 / 命令索引页 / 手册页目录”，优先把它作为自动发现种子，而不是手写所有子页面

当前项目里的经验：
- `QE / LAMMPS / GROMACS` 更适合 `git + parser`
- `OpenFOAM / Bioinformatics` 更适合 `manifest + curated entry pages`

### 2. 再定“接入粒度”

问自己三个问题：
- 用户会按什么名词来查：求解器、命令、参数、字典、子工具？
- `page_name` 应该怎么命名，未来最稳？
- `program / section / title` 该怎样存，`show/search` 才顺手？

经验规则：
- `page_name` 要服务 CLI 使用体验，不要只服务抓取方便
- 一个大页面如果天然包含很多独立参数，应该拆页
- 如果工具本来就是多子工具工具链，允许一个 top-level tool 下挂多个 `program`
- `program` 要优先贴近用户会说出的名字，而不是内部类名或目录名
- `section` 要反映用户排查问题时的思路，例如 `solver` / `dictionary` / `variant-calling`

从现有工具得到的粒度经验：
- `QE`：程序名 + namelist + 参数名，这样 `show qe pw ecutwfc` 才顺
- `LAMMPS`：命令家族一定要做 alias 聚合，不然 `fix npt` 这种自然输入会漂走
- `GROMACS`：`mdp` 参数页必须尽量保留 options，不然会变成只有变量名的空页
- `OpenFOAM`：不要一上来想抓完整站点，先抓 solver / dictionary / post-processing 关键页
- `Bioinformatics`：要承认它是 toolchain，不是单软件；先解决“路由到哪个子工具”

当目标从“最小可用”升级到“主体尽量全量”时：
- 不要继续人工堆 manifest
- 要升级成“seed pages -> automatic discovery -> snapshot manifest -> fetch/index”
- 对于单页大手册，要优先考虑按 anchor / heading 拆成逻辑页

### 3. 先做最小 manifest / parser，不要一上来追求全量

先做高价值页面：
- 最常用求解器或主程序
- 最关键配置字典或参数页
- 最关键模型页
- 1-2 个典型后处理或分析页

先让 `list/show/search` 真正可用，再扩充覆盖率。

停止条件也要明确：
- 如果高频真实查询已经稳定命中正确页，就不要为了“全站完整”无限扩张
- “生产级”不等于“把官网每一页都搬下来”
- 对 manifest 工具，优先做到“关键入口完整 + 网络失败不回退成残废状态”

如果用户明确要求“主体尽量全量”：
- 先定义主线边界，再自动扩展
- 例如：OpenFOAM 主体文档可以包含 fundamentals / tools 主线，但排除插件、挂件、开发者扩展
- 例如：Bioinformatics 工具链可以扩展官方子命令页、章节页、命令手册锚点，但不要把随机第三方生态也拖进来

### 4. TDD 先测 parser 和鲁棒性边角

最低应有测试：
- 解析器能提取 title / synopsis / content
- 版本或 program 规范化逻辑
- top-level `scrinium.toolref` 入口在内部重构后仍保持兼容
- manifest 工具的“是否完整”判断
- 失败后残缺目录不会被误判成已完成
- 用户自然说法对应的 alias / query expansion
- 缓存保留和 fallback URL 行为（如果是 manifest 工具）
- 自动发现规则（如果是 discovery-based manifest）
- anchor / heading 切片逻辑（如果是单页大手册拆分）
- `meta.json`、manifest 快照、SQLite 索引和 `toolref list` 展示口径一致

如果没有先看到失败场景，就不知道这个工具接入点真正脆不脆。

如果这次工作包含 `toolref` 内部重构或拆包，必须额外补这类兼容测试：

- `import scrinium.toolref` 后旧调用路径仍可用
- 顶层兼容 patch 点仍能影响真实行为
- CLI 不需要知道内部模块名变化
- 旧缓存数据库在新 schema / trigger 下不会损坏或重复触发

### 5. 实现 fetch/index/show/search 全链路

最低要求：
- `fetch` 能拉取并落盘
- `list` 能看到版本和页数
- `show` 能按用户自然输入命中
- `search` 能搜到高价值页面

重点防御：
- 网络失败后的残缺目录
- manifest 页面部分失败
- program 名规范化不一致
- 页面命名和用户输入不一致
- 同一概念的不同人话表达
- 主入口页失效后没有降级路径
- 包拆分后顶层兼容 facade 失效
- `fetch`、`index`、`list` 的计数口径漂移

manifest 工具的额外要求：
- 对高价值但不稳定的页面，允许配置 `fallback_urls`
- `force refresh` 不能把旧缓存中仍然可用的页面冲掉
- `meta.json` 要能说清楚：预期页数、失败页数、恢复自缓存的页数
- 自动发现得到的 manifest 必须落盘成快照，不能每次都重新“猜”一遍
- 发现阶段已经拿到的 HTML，正式抓取时应直接复用，避免二次下载
- 当外站超时但本地已有种子页缓存时，应该允许“用缓存继续做结构发现”
- 如果逻辑页来自单页手册的 anchor，正式抓取时要允许 `#anchor` 页面复用其基础 URL 的种子 HTML
- 预置高价值页名不一定等于真实 heading id；发现阶段要把真实 anchor 元数据回填到这些规范化 `page_name`
- `toolref list` 不能盲信过期 `meta.json`；必要时要与快照和实际索引自校准
- `fetch` 返回的索引数量要和最终库里的真实可查询条目数一致，而不是解析中间态数量

### 6. 必须做“真实使用体验”验证

不能只跑测试。必须像用户一样手动执行：

```bash
scrinium toolref fetch <tool>
scrinium toolref list <tool>
scrinium toolref show <tool> <natural query>
scrinium toolref search <tool> "<real query>"
```

检查：
- `show` 命中的是不是用户想看的页面
- 正文前是不是被导航噪音淹没
- `synopsis` 有没有信息量
- 首次失败后，第二次 `fetch` 是否会卡在脏目录
- 搜索是不是只“有结果”，还是首条结果就是对的
- 结果标题是不是能让用户一眼知道为什么它是对的
- 如果是工具链型工具，用户的描述能不能先路由到对的 `program`
- `fetch` 报的页数/条目数，和 `list` 看到的最终数值是否一致
- manifest 工具在旧缓存存在时，`list` 会不会出现自相矛盾的显示
- 对外入口是否仍然只需要 `scrinium toolref ...`，而不是内部模块命令

如果手感不好，就继续打磨 CLI；不要因为测试是绿的就停。

至少要抽查这三类真实查询：
- 参数名式：如 `ecutwfc`
- 自然语言式：如 `drag coefficient`、`v-rescale thermostat`
- 任务导向式：如 `read mapping nanopore`、`variant calling vcf`

如果做了“主体尽量全量”的扩展，还要加两类检查：
- 扩展后的总页数是否显著增加，而不是只换了实现没换覆盖面
- 扩展后 `show/search` 的核心路径是否仍然稳定，没有被噪音页挤掉

### 7. 再把对应 skill 改成轻量 `toolref-first`

对应 scientific `SKILL.md` 应只保留：
- 何时使用
- 高层工作流
- 科学规范
- `toolref` 查询入口
- agent 行为准则
- 覆盖缺口时如何退化处理

不要把 skill 写成第二份 API 手册。

分工应始终是：
- `skill = 路由 + 方法论 + 验证规范`
- `toolref = 官方接口与参数`
- `scientific-runtime = 运行时退化与用户体验协议`

不要把内部包结构泄漏到 skill：

- skill 和用户文档应该引用 `scrinium toolref ...`
- 如果确实需要提 Python API，引用顶层 `scrinium.toolref`
- 不要把 `fetch.py` / `manifest.py` / `storage.py` 之类内部模块写成公开入口

### 8. 最后做发布门槛检查

一个新工具只有同时满足下面几条，才算真正接入完成：
- 官方文档已入 `toolref`
- `fetch/list/show/search` 都能真实使用
- 至少有基础 parser 测试
- 对应 skill 已改成轻量 `toolref-first`
- 至少手动体验过一次端到端 CLI
- 如果做过内部重构，顶层兼容入口也已验证

如果你要判断“是否已经够生产，不要再打磨了”，就看这几条：
- 高频 `show` 查询能直接命中
- 高频 `search` 查询 rank 1 基本正确
- 本地重抓后不会把覆盖率越抓越差
- agent 不需要再让用户帮它维护文档
- 即使覆盖有缺口，runtime fallback 也能继续完成任务
- `fetch/list` 的统计口径不会把用户带沟里

满足这些，就应该把精力转回 demo 和真实科研任务，而不是继续无止境磨 `toolref`

## 常见错误

- 只看测试，不自己用 CLI
- 第一次抓取失败后没处理脏目录
- `page_name` 为抓取方便而设计，导致 `show` 很难用
- 内部拆包后忘了保护 `scrinium.toolref` 顶层兼容面
- 把 scientific skill 写成超长命令手册
- 新 skill 没有写清楚覆盖缺口时 agent 应如何继续服务用户
- 用第三方教程代替官方文档
- 把“能跑起来”误当成“生产级”
- 把“manifest 页数 100%”误当成“用户体验 100%”
- 忘记给易失联页面准备 fallback
- 工具链型工具没有先做路由，直接把所有子工具混在一起搜
- `fetch`、数据库真实条目数、和 `list` 展示数字彼此不一致

## 现有五个工具的经验教训

### QE

- 机器可解析的结构化文档价值极高
- `program + section + variable` 粒度一旦对了，`show` 体验会非常稳

### LAMMPS

- alias 是生产级体验的核心，不是装饰
- 用户说 `fix npt`，`show` 必须能稳稳落到 `fix_nh`，`search` 至少要把 `fix_nh` 放进最前排结果

### GROMACS

- 参数页不能只有变量名，必须保住 options 和代表性说明
- 排名正确不够，页面内容也要足够回答问题

### OpenFOAM

- 不要妄图第一次就镜像整站
- 先抓高价值入口页，配合好的 search alias，就能把体验快速拉起来
- 自动发现不应该把 curated 高价值入口覆盖掉；应该是扩充或升级它们
- 当用户真的要求“主体尽量全量”时，正确升级路径是：
  - 从官方主线文档页自动发现
  - 只保留主体路径
  - 把发现结果快照化
  - 用快照驱动后续抓取和页数判断

### Bioinformatics

- 首先要解决“这是哪一个子工具的问题”
- manifest 工具一旦跨多个站点，fallback 和缓存保留机制就不是可选项
- 单页大手册常常比“单独 man page 仓库”更有结构价值
- 对 `samtools / bcftools / iqtree` 这类工具，应该利用官方总目录页、命令索引、章节 anchor 自动扩页
- 网络不稳时，已有缓存不只是兜底数据，也应该成为 discovery 的输入
- 高价值规范名和真实 anchor id 可能不一致，例如用户会更自然地说 `ultrafast-bootstrap`，但上游文档的实际锚点可能是 `ultrafast-bootstrap-parameters`

## 生产级心态

面向 Scrinium 用户时，要始终记住：

- 用户不是来帮我们修 `toolref` 的
- 新工具接入的目标是让 agent 更自主，而不是把复杂性重新转嫁给用户
- 最终标准不是“代码优雅”或“页数很多”，而是 agent 是否真的更顺手、更可靠地完成科学任务
- 但如果用户明确要求更完整覆盖，就应该把“自动发现 + 快照 + 缓存复用 + 锚点拆页”做成正式能力，而不是继续靠人工列清单

## 快速检查清单

- 官方文档源已确认
- 版本策略已确认
- 解析粒度已确认
- parser 测试已写
- 顶层兼容入口已验证
- `fetch/list/show/search` 已手动体验
- 残缺目录问题已验证
- 高价值自然语言查询已验证
- `fetch`/`list` 计数口径已核对
- 如果有网络脆弱页面，fallback 已验证
- 如果是 discovery 型 manifest，快照写入与复用已验证
- 如果是单页大手册拆分，anchor 页面 `show/search` 已验证
- 对应 skill 已改成轻量结构
- 新 skill 与 `scientific-runtime` 协议兼容
- 最终再跑一次相关测试与 CLI smoke

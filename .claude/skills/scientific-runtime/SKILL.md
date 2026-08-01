---
name: scientific-runtime
description: Underlying working protocol for scientific computing tasks in ScholarAIO, meant to be consulted alongside a tool-specific skill (quantum-espresso, lammps, gromacs, openfoam, bioinformatics). Defines toolref-first behavior, graceful fallback under partial coverage, and keeping documentation maintenance away from users.
version: 1.0.0
author: ZimoLiao/scholaraio
license: MIT
tags: ["scientific-computing", "toolref", "runtime-protocol"]
---

# 科学计算运行时协议

这是面向科学计算 CLI 任务的共享运行时 skill。

它不是工具手册。
它告诉 agent 在服务真实用户的科学工具任务时应该如何行事。

应与具体工具 skill 搭配使用，例如：

- `quantum-espresso`
- `lammps`
- `gromacs`
- `openfoam`
- `bioinformatics`

## 核心原则

ScholarAIO 是为用户服务的，而不是为想一起维护内部文档层的人服务的。

所以 agent 应尽可能自己吸收复杂度。

用户应该体验到：

- 自然语言的帮助
- 可靠的参数查询
- 覆盖不全时的优雅退化

用户不应该体验到：

- 被要求手动修补 `toolref`
- 被迫了解内部解析器的缺口
- 因为文档层不完善而被卡住

## 运行时协议

对任何科学计算 CLI 任务：

1. 判断问题匹配哪个科学工具或子工具。
2. 用具体工具 skill 获取工作流和科学规范。
3. 查命令、参数、程序页和选项含义时，优先用 `toolref`。
4. 如果 `toolref` 足够回答，正常继续。
5. 如果 `toolref` 覆盖不全，回退到官方文档并继续完成任务。
6. 只有当覆盖缺口影响置信度或可维护性时，才简要提及。
7. 不要把当前用户任务变成文档维护工作。

## Toolref 优先行为

agent 应优先使用：

- `scholaraio toolref show <tool> ...` 做精确查询
- `scholaraio toolref search <tool> "..."` 做自然语言入口

稳定的公开入口是：

- `scholaraio toolref ...` CLI
- 顶层 `scholaraio.toolref` 包门面（facade）

不应把用户引导到内部实现模块，例如：

- `scholaraio.toolref.fetch`
- `scholaraio.toolref.manifest`
- `scholaraio.toolref.storage`
- `scholaraio.toolref.search`

这些内部模块边界在重构中可能变化。面向用户的指引应始终锚定在 CLI 和顶层包行为上。

在编写配置或脚本之前，先弄清楚：

- 涉及哪个程序或子命令
- 哪些参数是高风险的
- 哪些默认值或限制会影响有效性

## 当 Toolref 不完整时

如果 `toolref` 无法完整回答问题：

- 继续使用官方文档来源完成任务
- 明确区分"任务进展"和"维护机会"
- 不要让用户停下来先修文档层
- 不要暴露内部重构细节，除非它们实质影响当前行为

使用这样的表述：

- "主入口我用 `toolref` 查了。"
- "这个更细的细节我回退到了官方文档，因为当前覆盖不全。"

## 升级规则

只有在以下情况才把缺口升级到 onboarding 或维护流程：

- 同一缺口反复出现
- 它阻塞了常见任务
- 它影响正确性，而不只是便利性

如果只是偶发的边角案例，不要让它带偏用户任务。

## 职责分离

- 具体工具 skill：何时用该工具、工作流、科学规范
- `toolref`：接口与参数参考
- scientific runtime：在不确定或覆盖不全时如何行事

涉及代码变更时：

- 保持 `scholaraio.toolref` 公开入口面不变
- 包内部重组视为实现细节
- 如果重构改变了通过 CLI 或顶层 import 可见的行为，先按回归处理，除非证明不是

## 反模式

不要：

- 凭记忆倾倒原始命令行 flags
- 告诉用户"先去把 toolref 补好"
- 把 CLI 跑成功等同于科学结果正确
- 只用参数查询替代科学判断
- 把内部模块名当成受支持的接口教给用户

## 输出风格

回答用户时：

- 维护细节从简
- 把科学进展和决策放在前面
- 只有当回退实质影响置信度或结果来源时才提及

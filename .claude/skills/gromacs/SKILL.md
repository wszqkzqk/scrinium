---
name: gromacs
description: Use when working on biomolecular molecular dynamics with GROMACS, especially system setup, equilibration, production runs, trajectory analysis, or MM/PBSA-style post-processing.
version: 1.0.0
author: wszqkzqk/scrinium
license: MIT
tags: ["scientific-computing", "gromacs", "molecular-dynamics", "biomolecular"]
---

# GROMACS 分子动力学

用 GROMACS 做分子动力学模拟：从体系搭建、平衡、产出 MD 到轨迹分析和结合自由能评估。

本 skill **故意保持轻量**：
- 它负责告诉 agent 什么时候该用 GROMACS、标准工作流是什么、哪些科学规范不能踩
- 它**不**充当完整命令手册
- 具体命令行选项、`.mdp` 参数、子命令语法统一去查 `scrinium toolref`

本 skill 应与 `scientific-runtime` 一起理解：
- `gromacs` skill 负责生物分子 MD 路由、工作流和科学规范
- `scientific-runtime` 负责运行时的 `toolref-first` 行为和覆盖缺口退化策略
- `toolref` 负责子命令、选项和 `.mdp` 参数页

## Agent 默认协议（toolref-first）

对 GROMACS 问题，agent 默认按这个顺序工作：

1. 先判断问题属于哪一层：`gmx` 子命令、`.mdp` 参数、分析工具、力场/拓扑流程
2. 写 `.mdp` 前先查 thermostat、barostat、constraints、cutoff、输出频率这类高风险参数
3. 对用户自然语言说法，先 `search` 再 `show`
4. 如果 `toolref` 已经能回答，就不要在 skill 中重复堆参数表
5. 如果 `toolref` 缺页或命中不理想，agent 应先完成任务，并明确这是 `toolref` 覆盖缺口，而不是用户需要自己手动适配

这意味着：
- 普通用户不需要自己打磨 GROMACS 参数映射
- agent 应优先自己把 `Parrinello-Rahman`、`v-rescale thermostat`、`constraints h-bonds` 等问法映射到参数页
- `skill` 负责路线和规范，`toolref` 负责参数与接口

## 前置条件

```bash
# 安装
conda install -c conda-forge gromacs
# 配体参数化
conda install -c conda-forge acpype ambertools
# 结合自由能
pip install gmx-MMPBSA
# 可视化（可选）
conda install -c conda-forge pymol-open-source
```

验证：`gmx --version` 应显示版本号和 GPU 支持信息。

## 何时使用

适合：
- 蛋白-配体结合、蛋白构象变化、膜蛋白、溶液中生物大分子
- 需要标准 MD 流程、轨迹分析、MM/PBSA 估算

不适合：
- 需要量子化学精度时，转 DFT / QM/MM
- 配体参数化来源不明、力场体系不一致时，不要直接推进

## Toolref 优先

当 agent 不确定子命令、选项、`.mdp` 参数含义时，**先查 toolref**。

常用查法：

```bash
scrinium toolref search gromacs "temperature coupling"
scrinium toolref show gromacs mdp integrator
scrinium toolref show gromacs mdp pcoupl
scrinium toolref show gromacs mdp tau-t
scrinium toolref show gromacs mdp ref-t
```

推荐习惯：
- 写 `.mdp` 前，先逐项查核心参数
- 不靠记忆拼写 thermostat/barostat 选项
- 对“这项参数在当前版本是否还推荐”这类问题，优先相信 `toolref` 而不是旧教程

如果遇到覆盖缺口：
- 先继续使用 GROMACS 官方文档完成任务
- 在输出中点明这里超出了当前 `toolref` 覆盖
- 不要把补齐 `toolref` 当成普通用户的前置工作

## 核心流程

### 知识库协作模式

这是本 skill 与普通 GROMACS 教程的核心区别。**在任何模拟开始前：**

1. 用 `scrinium usearch "<体系关键词>"` 检索知识库中的相关论文
2. 从论文中提取：力场选择依据、模拟参数（温度、压力、时长）、验证基准数据
3. 在 `.mdp` 文件注释中标注参数来源（如 "# 300 K, per Homeyer et al. 2014 JCTC"）
4. 模拟完成后，将结果与论文数据定量对比

建议工作流：
1. 读论文，确定力场、温压条件、盐浓度、模拟时长和验证指标
2. 准备蛋白/配体结构与拓扑
3. 构建溶剂盒并加离子
4. 能量最小化
5. NVT / NPT 平衡
6. 产出 MD
7. 轨迹分析
8. 必要时做 MM/PBSA，并和文献/实验对比

典型输出：
- RMSD / RMSF / 氢键 / 回旋半径
- 关键构象快照或轨迹动画
- 结合自由能及误差条
- 对应文献基准的对比图

### 常见查询点

- `.mdp` 核心参数：`integrator`, `dt`, `pcoupl`, `tcoupl`, `tau-t`, `ref-t`
- 产出阶段系综设置
- PME / cutoff / 压缩轨迹输出参数
- 不同版本对 thermostat/barostat 的推荐配置

这些都应优先通过 `toolref` 查询，而不是写死在 skill 里。

## 科学规范（专家级检查清单）

| 检查项 | 正确做法 | 常见错误 |
|--------|---------|---------|
| 力场 | CHARMM36m 或 AMBER ff19SB | 用过时的 OPLS-AA |
| 配体参数化 | GAFF2 + AM1-BCC (ACPYPE) | 自动生成的垃圾拓扑 |
| 力场一致性 | 全 AMBER 或全 CHARMM，**不混用** | CHARMM 蛋白 + GAFF 配体 |
| 产出恒压器 | Parrinello-Rahman | 产出阶段用 Berendsen |
| 盒子形状 | 十二面体（省 30% 水） | 立方体 |
| 离子浓度 | 0.15 M NaCl | 只中和电荷不加盐 |
| MM/PBSA 取样 | 最后 10 ns（平衡后） | 用整条轨迹 |
| 误差报告 | ΔG ± σ | 只报单个值 |

附加规范：
- 平衡阶段和产出阶段不要混用目标不同的耦合设置而不说明理由
- 配体参数化来源必须可追溯
- 报告结果时不要只给一条 RMSD 曲线，要回到生物物理问题本身

## 可视化

| 工具 | 用途 |
|------|------|
| PyMOL | 结合口袋特写、氢键、光线追踪静态图 |
| VMD | 轨迹动画、表面渲染 |
| matplotlib | RMSD/RMSF/能量时间序列、验证对比图 |
| nglview | Jupyter 中交互式 3D |

## 性能参考

| 体系大小 | GPU 配置 | 预期性能 |
|----------|---------|---------|
| ~45k 原子 | 1×A100 | ~150 ns/day |
| ~45k 原子 | 4×A100 | ~400-600 ns/day |
| ~100k 原子 | 4×A100 | ~200-300 ns/day |

## Agent 行为准则

- 不要背诵 `.mdp` 参数，查 `toolref`
- 不要把“跑完轨迹”当成完成，必须给稳定性和机制解释
- 不要忽略力场一致性问题
- 不要把 MM/PBSA 单值当结论，必须报告区间和误差

---
name: lammps
description: Use when working on classical materials simulations with LAMMPS, especially interatomic-potential selection, shock or deformation setups, thermodynamic runs, and structure analysis for solids or nanomaterials.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["scientific-computing", "lammps", "molecular-dynamics", "materials"]
---

# LAMMPS 材料科学模拟

用 LAMMPS 做材料科学分子动力学模拟：晶体构建、势函数选择、形变/冲击、结构分析、可视化。

本 skill **故意保持轻量**：
- 它负责告诉 agent 什么时候该用 LAMMPS、该遵守什么科学规范、完整工作流长什么样
- 它**不**承担完整接口手册的职责
- 具体命令、参数、语法、package 限制，统一去查 `scrinium toolref`

本 skill 应与 `scientific-runtime` 一起理解：
- `lammps` skill 负责经典 MD 路由、工作流和科学规范
- `scientific-runtime` 负责运行时的 `toolref-first` 行为和覆盖缺口退化策略
- `toolref` 负责命令、参数页和 package 限制说明

## Agent 默认协议（toolref-first）

对 LAMMPS 问题，agent 默认按这个顺序工作：

1. 先判断问题属于哪类对象：`pair_style`、`fix`、`compute`、`dump`、`region`、`boundary`、`run` 流程
2. 写输入脚本前，优先查高风险命令页，而不是凭记忆拼装
3. 命令名和用户说法不一致时，优先用 `search` 找主入口，再用 `show`
4. 如果 `toolref` 已能回答，就不要在 skill 里重复写手册
5. 如果 `toolref` 命中不好或某个 package 页面缺失，agent 应先完成任务，再把它标记为维护层缺口，而不是让用户自己补

这意味着：
- 用户不该自己去打磨 `fix` / `pair_style` 的映射关系
- agent 应自己消化 `fix npt -> fix_nh`、`pair style eam -> pair_eam` 这类入口差异
- 只有反复出现的缺口才进入正式 onboarding

## 前置条件

```bash
# 安装（含 GPU 支持）
conda install -c conda-forge lammps
# 可视化
pip install ovito
```

验证：`lmp -h` 应显示已安装的 packages（需包含 GPU、MANYBODY、EXTRA-COMPUTE）。

GPU 加速：`package gpu 4` 在输入脚本开头启用，`suffix gpu` 自动为支持的 pair_style 加 `/gpu` 后缀。

并行运行约束：
- 启动 MPI 作业时，优先使用 **LAMMPS 所在环境自带的** `mpirun/mpiexec`
- 不要默认混用系统里的另一套 MPI launcher；如果 `lmp` 链接的 `libmpi` 与 launcher 不一致，可能出现“进程活着但无日志输出”的假启动挂起
- 需要绑核或做 rank pinning 时，先用小规模 MPI 诊断确认启动和绑定语法，再放大到正式规模

## 何时使用

适合：
- 金属、陶瓷、半导体、纳米材料的经典 MD
- 力学性质、相变、位错/缺陷演化、冲击波、热输运
- 已有合适经验势函数的体系

不适合：
- 需要显式电子结构精度时，优先考虑 DFT / Quantum ESPRESSO
- 势函数没有可靠文献依据时，不要直接开算

## Toolref 优先

当 agent 不确定命令、参数、限制、输出字段时，**先查 toolref，再写输入脚本**。

常用查法：

```bash
scrinium toolref search lammps "nose hoover thermostat"
scrinium toolref show lammps fix_nh
scrinium toolref show lammps pair_eam
scrinium toolref show lammps compute_cna_atom
scrinium toolref show lammps fix_deform
```

推荐习惯：
- 写脚本前先查 `pair_style` / `fix` / `compute` / `dump`
- 遇到 package 依赖时先用 `toolref show` 看 Restrictions
- 遇到模糊概念先用 `toolref search`，确定候选命令后再 `show`

如果遇到覆盖缺口：
- 先用官方 LAMMPS 文档继续完成任务
- 明确说明这里是 `toolref` 覆盖/排序缺口，不是用户操作错误
- 不要让用户为了当前任务先停下来维护文档层
- 如果官方手册没有解释清楚实际运行异常、MPI 启动问题、版本兼容或绑定语法，继续上网检索官方文档、社区讨论和已知问题，不要猜

## 核心流程

### 知识库协作模式

1. 用 `scrinium usearch "<材料/现象>"` 检索相关论文
2. 从论文提取：势函数选择、晶格常数、实验基准值（相变压力、弹性常数等）
3. 在输入脚本注释中标注参数来源
4. 计算完成后与文献数据定量对比

建议按这个顺序思考：
1. 体系是否适合经典势函数
2. 选择哪类势函数
3. 选择边界条件、加载方式、温压控方式
4. 选择结构分析与输出
5. 跑小体系/短步数 smoke test
6. 正式运行后和文献/实验做定量对比

参数出处规则：
- 严格复现任务里，先查库内已入库论文和补充材料
- 如果关键参数仍然缺失，需要别的论文或 supplementary 才能定死，应直接向用户明确索取，不要猜
- 只有当文献明确允许范围选择时，才可以做工程性取值，并要说明这是“派生设置”而不是“严格复现参数”

### 势函数选择（最关键决策）

| 势函数类型 | 适用场景 | LAMMPS pair_style |
|-----------|---------|-------------------|
| EAM/FS | 金属（Fe, Cu, Al, Ni...） | `eam/fs`, `eam/alloy` |
| Tersoff | 共价半导体（Si, C, SiC） | `tersoff` |
| ReaxFF | 反应性体系（燃烧、氧化） | `reaxff` |
| AIREBO | 碳纳米材料（CNT, 石墨烯） | `airebo` |
| SW | Si, GaN | `sw` |
| MEAM | 多元合金 | `meam` |

**势函数文件来源：**
- NIST Interatomic Potentials Repository: https://www.ctcms.nist.gov/potentials/
- LAMMPS potentials/ 目录（随发行版附带）
- 论文 supplementary material

**科学规范：势函数选择必须有文献依据，不能随便选一个"能跑"的。**

### 典型任务

- 冲击波 / 爆轰 / 高应变率：重点看非周期边界、活塞施加方式、空间剖面输出
- 拉伸压缩：重点看 `fix deform`、应力应变提取、应变率合理性
- 温度驱动相变：重点看升温速率、平衡充分性、结构识别
- 缺陷与位错：重点看结构分析和可视化，不只看总能量

常用结构分析：
- `cna/atom`：区分 BCC/FCC/HCP
- `ptm/atom`：更稳健的局域结构识别
- `centro/atom`：缺陷检测
- `voronoi/atom`：局域环境统计

这些命令的准确接口、参数和限制请直接查 `toolref`。

## 可视化（OVITO）

OVITO 是 LAMMPS 的标准可视化工具。

```python
from ovito.io import import_file
from ovito.modifiers import CommonNeighborAnalysisModifier, SliceModifier
from ovito.vis import Viewport, TachyonRenderer

pipeline = import_file("dump.shock.*", sort_particles=True)
pipeline.modifiers.append(CommonNeighborAnalysisModifier())

# 按结构类型着色
def color_by_phase(frame, data):
    import numpy as np
    colors = np.zeros((data.particles.count, 3))
    cna = data.particles["Structure Type"]
    colors[cna == 3] = [0.3, 0.5, 0.8]   # BCC → 蓝
    colors[cna == 2] = [0.85, 0.15, 0.15] # HCP → 红
    colors[cna == 1] = [0.2, 0.8, 0.2]    # FCC → 绿
    colors[cna == 0] = [0.7, 0.7, 0.7]    # Other → 灰
    data.particles_.create_property("Color", data=colors)

pipeline.modifiers.append(color_by_phase)

vp = Viewport(type=Viewport.Type.ORTHO, camera_dir=(0, -1, 0))
vp.zoom_all(size=(1920, 1080))
renderer = TachyonRenderer(shadows=False, ambient_occlusion=True)
vp.render_image(filename="snapshot.png", size=(1920, 1080), renderer=renderer)
```

推荐输出：
- 结构类型着色快照或动画
- 应力/温度/速度的空间剖面图
- 与文献基准的对比图，而不是只给一张原子图

## 性能参考

| 体系大小 | 势函数 | GPU 配置 | 预期性能 |
|----------|--------|---------|---------|
| ~500k 原子 | EAM | 4×A100 | ~50 ns/day |
| ~2M 原子 | EAM | 4×A100 | ~15-20 ns/day |
| ~100k 原子 | ReaxFF | 4×A100 | ~1-2 ns/day |

## 科学规范

| 检查项 | 正确做法 | 常见错误 |
|--------|---------|---------|
| 势函数 | 有文献验证的 EAM/Tersoff | 随便选一个 LJ |
| 体系大小 | 足够消除有限尺寸效应 | 太小导致伪周期 |
| 平衡 | 先 NPT 平衡再施加载荷 | 直接拉伸未平衡体系 |
| 时间步长 | metal 单位下 0.001 ps (1 fs) | 步长太大导致能量不守恒 |
| 边界条件 | 冲击方向用 `s`（非周期） | 全周期导致冲击波自干涉 |
| 截断半径 | 根据势函数要求设置 | 用默认值不检查 |

## Agent 行为准则

- 不要凭记忆瞎写 `fix` / `compute` / `pair_style` 细节，先查 `toolref`
- 不要因为“能跑”就默认模型合理，必须说明势函数和参数依据
- 不要只汇报温度/能量曲线，要给结构、相分数、应力或波前等材料学指标
- 不要把 LAMMPS 当黑箱；结果解释必须回到材料机制

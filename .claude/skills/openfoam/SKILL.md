---
name: openfoam
description: Use when working on CFD cases with OpenFOAM, especially solver selection, dictionary setup, mesh workflow decisions, turbulence-model choices, and verification of fluid-flow or heat-transfer simulations.
version: 1.0.0
author: wszqkzqk/scrinium
license: MIT
tags: ["scientific-computing", "openfoam", "cfd", "turbulence"]
---

# OpenFOAM 计算流体力学

用 OpenFOAM 做 CFD：从 case 结构、网格、求解器、湍流模型到后处理和验证。

本 skill **故意保持轻量**：
- 它负责告诉 agent 什么时候该用 OpenFOAM、标准工作流是什么、哪些 CFD 规范不能忽略
- 它**不**充当完整字典/求解器手册
- 具体求解器页面、字典字段、模型说明统一去查 `scrinium toolref`

本 skill 应与 `scientific-runtime` 一起理解：
- `openfoam` skill 负责 CFD 路由、工作流和科学规范
- `scientific-runtime` 负责运行时的 `toolref-first` 行为和覆盖缺口退化策略
- `toolref` 负责官方入口页、求解器页、字典页和模型页

当前成熟度：**`toolref-first, partial coverage`**

## Agent 默认协议（toolref-first, partial coverage）

OpenFOAM 当前的 `toolref` 适合做**主入口查询**，但还不是完整手册替代。

对 OpenFOAM 问题，agent 默认按这个顺序工作：

1. 先判断用户问题属于哪一层：
   - 求解器选择
   - case 骨架与目录结构
   - `fvSchemes` / `fvSolution` / `controlDict`
   - 湍流模型
   - 网格与前处理
   - 后处理与验证
2. 先用 `toolref` 查主求解器、主字典和高价值模型页
3. 对 `simpleFoam` / `pimpleFoam` / `fvSchemes` / `fvSolution` / `controlDict` / `kOmegaSST` / `blockMesh` / `snappyHexMesh` / `forceCoeffs` / `Q` 这类主入口，优先信任 `toolref`
4. 如果 `show` 没有直接命中 solver / function object 主页，或结果明显退化成模糊页，立即回退到官方文档
5. 回退时要明确说明这是当前 OpenFOAM `toolref` 覆盖较浅，而不是用户用法有问题
6. 不要要求普通用户为了当前任务先自己维护 OpenFOAM 文档层

这意味着：
- `toolref` 先解决“找对入口”的问题
- 细粒度深挖可以暂时回退官方文档
- agent 应主动吸收这种复杂度，不要转嫁给用户
- 在真实任务里，优先保证 case 正确性、物理合理性和验证闭环，而不是追求文档层完美无缺

## 前置条件

```bash
# 安装（Ubuntu/WSL2）
sudo apt install openfoam
# 或 Docker
docker pull openfoam/openfoam-dev

# 可视化
sudo apt install paraview
```

验证：`simpleFoam -help` 应正常输出。确认 `$WM_PROJECT_DIR` 环境变量已设置。

## 何时使用

适合：
- 外流、内流、传热、稳态/瞬态 RANS 或更复杂的 CFD 工作流
- 需要几何建模、网格控制、边界条件和场量后处理的工程问题

不适合：
- 只需要快速低保真估算、且不打算做网格无关性和验证时
- 物理模型选择没有依据、只想“先跑起来再说”的情况

## Toolref 优先

当 agent 不确定求解器、字典、function object、湍流模型时，**先查 toolref**。

常用查法：

```bash
scrinium toolref show openfoam simpleFoam
scrinium toolref show openfoam pimpleFoam
scrinium toolref show openfoam controlDict
scrinium toolref show openfoam fvSchemes
scrinium toolref show openfoam fvSolution
scrinium toolref show openfoam kOmegaSST
scrinium toolref show openfoam blockMesh
scrinium toolref show openfoam snappyHexMesh
scrinium toolref show openfoam forceCoeffs
scrinium toolref search openfoam numerical schemes
scrinium toolref search openfoam linear solver settings
scrinium toolref search openfoam turbulence model
scrinium toolref search openfoam drag coefficient
scrinium toolref search openfoam q criterion
```

推荐习惯：
- 写 case 前先查 solver、字典和模型主入口
- 改 `fvSchemes` / `fvSolution` 前先看官方字典说明
- 讨论湍流模型时优先查官方模型页，而不是凭论坛记忆
- 做后处理前先查 `forces` / `forceCoeffs` / `yPlus` / `Q` 这类入口页
- 如果 solver / function object 页没有直接命中，不要硬猜，直接回退官方文档

最低运行规则：
1. 先用 `toolref show` 命中主入口
2. 不确定自然语言映射时，再用 `toolref search`
3. 命中主入口后，先做最小 smoke case，再扩到正式算例
4. 如果 `toolref show` 没法直接落到目标页，或 `search` 结果明显不对题，再回退官方文档

如果遇到覆盖缺口：
- 先继续用 OpenFOAM 官方文档完成当前任务
- 回答时点明这是 `toolref` 深度覆盖不足
- 只有当同类缺口反复出现，才进入正式 onboarding/补页流程
- 不要把“请用户一起补文档”当成默认下一步

## 核心工作流

### 知识库协作模式

1. 用 `scrinium usearch "<流动问题>"` 检索相关论文
2. 从论文提取：几何参数、流动条件（Re, Ma）、湍流模型选择依据、验证数据
3. Case 设置中标注参数来源
4. 计算完成后与实验/DNS 数据定量对比（速度剖面、阻力系数、压力分布）

建议工作流：
1. 读论文/实验资料，确定几何、Re、边界条件、验证指标
2. 选求解器和湍流模型，并说明为什么不是别的候选
3. 建网格并做质量检查
4. 配置 `controlDict / fvSchemes / fvSolution`
5. 跑小规模 smoke case 看是否发散
6. 做正式计算
7. 检查残差、力系数、剖面和 y+
8. 与实验 / DNS / 文献做定量对比

对 agent 的最小交付要求：
- 不只给一个能跑的 case
- 要说清楚求解器、湍流模型、边界条件、网格策略为什么这样选
- 要明确最后拿什么指标验证，不允许只说“残差下来了”

### 求解器选择

| 求解器 | 适用场景 |
|--------|---------|
| `simpleFoam` | 稳态不可压 RANS |
| `pimpleFoam` | 瞬态不可压（LES/URANS） |
| `rhoSimpleFoam` | 稳态可压 |
| `sonicFoam` | 瞬态可压/超声速 |
| `buoyantSimpleFoam` | 自然对流/传热 |
| `interFoam` | 两相流（VOF） |
| `reactingFoam` | 燃烧/反应流 |

### 湍流模型

| 模型 | 适用场景 | 何时选用 |
|------|---------|---------|
| `kOmegaSST` | **默认首选**，外流/分离流 | 大多数工程问题 |
| `kEpsilon` | 内流/充分发展流 | 管道、通道 |
| `SpalartAllmaras` | 航空外流 | 翼型、薄边界层 |
| `kOmegaSSTLM` | 转捩流动 | 低 Re 翼型 |
| `Smagorinsky` / `WALE` | LES 亚格子模型 | 需要瞬态细节时 |

**科学规范：湍流模型选择必须有文献依据或物理论证。不能"试了几个选最好看的"。**

### 重点查询点

- `simpleFoam` / `pimpleFoam` / `rhoSimpleFoam` 的适用边界
- `fvSchemes` 和 `fvSolution` 的关键项
- `kOmegaSST` 等湍流模型的物理假设
- `function objects`、`forces`、`yPlus` 的用法
- `blockMesh` / `snappyHexMesh` 的职责边界
- `forceCoeffs` 和 `Q` 这类后处理入口对象

这些细节优先查 `toolref`，不要在 skill 里硬背。

## ParaView 可视化

```python
# pvpython 自动化脚本
from paraview.simple import *

# 加载 OpenFOAM case
reader = OpenFOAMReader(FileName="<case>/case.foam")
reader.UpdatePipeline()

# 表面压力云图
display = Show(reader)
display.SetRepresentationType("Surface")
ColorBy(display, ("CELLS", "p"))
pLUT = GetColorTransferFunction("p")
pLUT.ApplyPreset("Cool to Warm", True)

# 切面
slice = Slice(reader)
slice.SliceType.Normal = [0, 1, 0]  # y=0 对称面
Show(slice)
ColorBy(GetDisplayProperties(slice), ("CELLS", "U", "Magnitude"))

# 渲染
view = GetActiveView()
view.ViewSize = [3840, 2160]
SaveScreenshot("pressure_surface.png", view)
```

## 科学规范

| 检查项 | 正确做法 | 常见错误 |
|--------|---------|---------|
| 网格无关性 | 至少跑粗/中/细三套网格 | 只用一套网格 |
| y+ | 检查并确认在壁面函数范围内 | 不检查 y+ |
| 收敛 | 残差降 3-4 个量级 + 力系数稳定 | 只看残差不看积分量 |
| 域大小 | 出口距物体 >5-8L | 域太小影响尾流 |
| 迎风格式 | linearUpwind（二阶） | 全用一阶迎风（数值耗散过大） |
| 验证 | 与实验/DNS 数据逐点对比 | "看起来对"就算验证 |

## Agent 行为准则

- 不要凭感觉选求解器或湍流模型，先查 `toolref` 并说明依据
- 不要只盯残差，必须同时看积分量、剖面和 y+
- 不要把“收敛了”当“正确了”，验证必须回到实验或基准算例
- 不要把 OpenFOAM 当配置文件游戏，结果解释必须回到流体力学
- 不要把 `toolref` 的覆盖缺口转嫁给用户；能回退官方文档就先完成用户任务

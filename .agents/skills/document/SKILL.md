---
name: document
description: Generate and inspect Office documents (DOCX, PPTX, XLSX). Generate by writing Python scripts that call python-docx, python-pptx, and openpyxl APIs directly. Inspect with `scrinium document inspect` to verify layout, content, and catch issues (overflow, missing elements). Use when the user wants to create Word reports, PowerPoint presentations, Excel data sheets, or inspect any Office document.
version: 1.0.0
author: wszqkzqk/scrinium
license: GPL-3.0-or-later
tags: ["document", "docx", "pptx", "xlsx", "office", "report"]
---

# Office 文档生成与检查

直接用 Python API 生成 Word / PowerPoint / Excel 文档，并通过 `scrinium document inspect` 检查文档结构和布局。

## 何时使用

适用：
- 生成正式 Word 报告、简报、带 TOC 的综述文档
- 生成 PowerPoint 汇报 / 答辩幻灯片
- 生成带样式、筛选、图表的 Excel 数据表
- 检查任何 Office 文档的结构与布局问题（溢出、缺失元素）

不适用：
- 简单的 Markdown → DOCX 转换（用 `scrinium export docx`，见 `/export` skill）
- 纯 Markdown 写作（直接写 `.md` 即可，无需 Office 文档）

## 核心思路

**生成**：不要用 `scrinium export docx`（那个只是简单的 Markdown 转换器）。本 skill 直接编写 Python 脚本调用 Office 库 API，类似 draw skill 直接调用 Inkscape API 画图。

**检查**：生成后必须用 `scrinium document inspect <file>` 检查文档，确认布局、内容、图片尺寸无误，再交付给用户。

输出目录：`workspace/` 下（如 `workspace/reports/`、`workspace/figures/`）。

## 选型决策

| 需求 | 格式 | 库 |
|------|------|-----|
| 报告 / 综述 / 简报 / 论文 | DOCX | `python-docx` |
| 汇报 / 演示 / 答辩 | PPTX | `python-pptx` |
| 数据表 / 统计 / 列表 | XLSX | `openpyxl` |

用户未指定时按内容性质选择，默认 DOCX。

**详细 API 速查与可运行模板见 [reference.md](reference.md)**（三个库的导入方式、文档结构模板、API 速查表、TOC 字段、表格样式、图表等），写生成脚本时按需加载，不必预读。

## 执行逻辑（生成 → inspect 闭环）

1. **判断输出格式**：按上表选型
2. **收集内容**：调用其他 skill/CLI 获取数据
   - `scrinium search` — 搜索论文
   - `scrinium show --layer 2/3` — 获取摘要/结论
   - `scrinium top-cited` — 高引论文
   - `scrinium topics <tag>` — 主题（标签）下的论文
   - `scrinium workspace show <name>` — 工作区论文列表
3. **生成图表**（如需要）：用 draw skill 生成 PNG/SVG 到 `workspace/figures/`
4. **编写 Python 脚本**：参照 [reference.md](reference.md) 中对应库的模板与 API 速查，在一个脚本中完成全部操作
5. **输出到 `workspace/`**：
   ```
   workspace/
   └── reports/
       ├── research_brief.docx
       ├── presentation.pptx
       └── paper_stats.xlsx
   ```
6. **检查文档**：运行 `scrinium document inspect <file>` 检查生成结果
   - PPTX：确认图片未溢出、文字未超出容器、布局合理
   - DOCX：确认标题层级正确、表格完整、图片已嵌入
   - XLSX：确认数据完整、图表标题正确、冻结窗格生效
   - 如发现问题 → 修改脚本 → 重新生成 → 再次 inspect
7. **告知用户**输出路径

## 文档检查（inspect）

```bash
# 检查 PPTX：逐页输出 shape 位置/尺寸/文字/图片信息 + 溢出警告
scrinium document inspect presentation.pptx

# 检查 DOCX：段落/标题/表格/图片结构 + 样式摘要
scrinium document inspect report.docx

# 检查 XLSX：Sheet 概览 + 数据预览 + 图表列表
scrinium document inspect data.xlsx
```

**输出内容**：

| 格式 | 检查项 |
|------|--------|
| PPTX | 每页 shape 类型、位置(英寸)、尺寸、文字预览、图片大小、表格维度、**溢出检测** |
| DOCX | 标题层级、段落内容、表格结构、嵌入图片、样式统计 |
| XLSX | Sheet 列表、数据范围、冻结窗格、合并单元格、表头预览、数据预览、图表类型和标题 |

## 与其他 skill 的组合

| 组合 | 流程 |
|------|------|
| draw + document | draw 生成 PNG/SVG → `doc.add_picture()` 嵌入 DOCX/PPTX |
| search + document | 搜索结果 → 表格写入 DOCX/XLSX |
| literature-review + document | 生成综述内容 → 带 TOC 的正式 Word 文档 |
| paper-writing + document | 论文章节 → 排版完整的 Word 文件 |
| topics + document | 主题分析 → 可视化报告（PPTX 幻灯片） |

## 快捷方式

对于简单的 Markdown → DOCX 转换（不需要高级排版），仍可使用：
```bash
scrinium export docx --input file.md --output file.docx
```

## 示例

用户说："帮我总结一下文献库，写个简报到 Word 文件"
→ 调用 `top-cited`、`topics`、`insights` 收集数据 → 参照 reference.md 写 python-docx 脚本生成带标题、目录、表格、图片的 DOCX

用户说："把 phd-thesis 工作区的论文做成 PPT 给导师汇报"
→ 调用 `workspace show phd-thesis` 获取论文列表 → 按主题分组 → 参照 reference.md 写 python-pptx 脚本生成幻灯片

用户说："导出所有论文的统计数据到 Excel"
→ 遍历 `data/papers/*/meta.json` 提取字段 → 参照 reference.md 写 openpyxl 脚本生成带筛选和图表的 XLSX

用户说："画一个流程图然后嵌入到报告里"
→ 先用 draw skill 生成 PNG → 再用 python-docx 的 `add_picture()` 嵌入 DOCX

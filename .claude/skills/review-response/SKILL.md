---
name: review-response
description: Draft point-by-point responses to peer review comments. Locates supporting evidence from workspace papers and the original manuscript. Use when the user receives reviewer feedback and needs to write a rebuttal or revision response letter.
version: 1.0.0
author: wszqkzqk/scrinium
license: MIT
tags: ["academic", "writing", "peer-review", "rebuttal"]
---
# 审稿回复

逐条回复审稿人意见，从工作区文献和原稿中定位支撑证据。

## 前提

用户需提供：
1. **审稿意见**：粘贴或文件路径
2. **原稿**：workspace 中的论文草稿或文件路径
3. **workspace**：关联的文献工作区（用于检索支撑证据）
4. **语言**：中文 / English（回复信通常与原稿语言一致）

## 执行逻辑

### 1. 解析审稿意见

将审稿意见拆分为独立的 comment，分类标注：
- **MAJOR**：需要实质性修改（补实验、改方法、加分析）
- **MINOR**：表述修改、格式调整、补充说明
- **POSITIVE**：正面评价（致谢即可）
- **QUESTION**：需要回答的问题

### 2. 逐条分析

对每条意见：
1. 理解审稿人的核心诉求
2. 在原稿中定位相关段落
3. 用 `scrinium show` 查看论文（已有 `notes.md` 笔记会自动展示），复用已有发现
4. 在工作区文献中搜索支撑证据：
   ```bash
   scrinium ws search <name> "<审稿人关注的关键词>"
   scrinium show <paper-id> --layer 3      # 读结论找证据
   scrinium show <paper-id> --layer 4      # 必要时读全文
   ```
5. 从引用图谱中找额外支撑：
   ```bash
   scrinium refs "<id>"                    # 相关论文的参考文献
   scrinium usearch "<补充关键词>"          # 全库搜索（工作区外）
   ```

### 3. 撰写回复

每条回复的结构：

```
> **Reviewer X, Comment N:** [原文引用]

**Response:** [回复正文]

[如有修改] **Revision:** We have revised Section X.X as follows: "..." (Page X, Line X)
```

回复策略：
- **同意并修改**：明确说明做了什么修改、在哪里
- **部分同意**：承认合理之处，解释为什么不完全采纳，提供证据
- **礼貌反驳**：用数据和文献支撑，语气尊重但立场坚定
- **补充实验/分析**：描述新增的内容和结果

**多模态辅助**：
- 审稿人质疑图表时，读取论文中的原始图（`images/`）重新分析
- 审稿人质疑数值时，编写 Python 代码独立复现计算，用代码输出作为回复证据
- 审稿人质疑推导时，读取论文中的公式逐步验证

### 4. 输出

- 保存回复信到 `workspace/<name>/response-letter.md`
- **必须**通过 CLI 将深度分析的论文关键发现写入笔记：
  ```bash
  scrinium show "<paper-id>" --append-notes "## YYYY-MM-DD | <workspace> | review-response
  - 关键发现"
  ```
- 如需补充引用新论文到工作区：
  ```bash
  scrinium ws add <name> <paper-id>
  ```

## 写作原则

- **逐条回复，不遗漏**：每条意见都必须有明确回应
- **证据优先**：能用数据和文献回答的，不用空话
- **语气专业**：感谢审稿人的建设性意见，即使不同意也保持尊重
- **修改可追踪**：明确标注修改位置（Section、Page、Line）
- **引用核验**：提交前用 `/citation-check` 检查回复信中新增或改动过的 author-year 引用
- **不回避弱点**：如果审稿人指出的确是问题，坦诚承认并说明改进措施

## 示例

用户说："审稿意见回来了，帮我写 response letter"
→ 解析意见，分类标注，逐条在工作区中找证据，撰写回复

用户说："Reviewer 2 说我的方法跟 Smith (2023) 没区别，怎么回"
→ 在工作区中找到 Smith (2023)，对比方法差异，起草有理有据的反驳

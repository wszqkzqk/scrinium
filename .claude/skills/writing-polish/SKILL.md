---
name: writing-polish
description: Polish academic writing — remove AI-generated patterns, improve clarity, and match a target style. Supports both English and Chinese. Use when the user wants to refine prose, remove AI artifacts, or adapt writing to a specific journal style.
version: 1.0.0
author: wszqkzqk/scrinium
license: MIT
tags: ["academic", "writing", "polish", "style"]
---
# 学术写作润色

去除 AI 痕迹、提升表达质量、匹配目标风格。支持中英文。

## 执行逻辑

### 1. 了解需求

向用户确认：
- **待润色文本**：粘贴、文件路径、或 workspace 中的文件
- **润色方向**：去 AI 味 / 学术规范 / 风格适配 / 全部
- **目标语言**：中文 / English（是否需要翻译）
- **风格参考**（可选）：用户提供同期刊/同领域的范文，你来提取风格特征并仿照

### 2. 风格分析（如有范文）

当用户提供风格参考时，先分析范文的：
- **句式特征**：句子平均长度、主动/被动语态比例、从句嵌套深度
- **术语习惯**：领域专用词的选择偏好（如 "utilize" vs "use"）
- **段落结构**：每段几句话、topic sentence 位置、过渡方式
- **引用风格**：引用密度（每段几处）、引用位置（句首/句中/句尾）
- **形式化程度**：口语化 vs 高度形式化

将分析结果展示给用户确认，然后据此润色。

### 3. AI 痕迹检测与消除

常见 AI 写作模式（必须消除）：

**英文：**
- 空洞开头："In recent years, X has garnered significant attention..."
- 过度连接词："Furthermore", "Moreover", "It is worth noting that"
- 虚假精确："a myriad of", "a plethora of", "a paradigm shift"
- 套话结尾："paving the way for future research"
- 过度对称的段落结构（每段长度几乎相同）
- 不必要的元叙述："This section discusses...", "As mentioned above..."

**中文：**
- "值得注意的是"、"不可忽视的是"
- "近年来，X引起了广泛关注"
- "具有重要的理论意义和实践价值"
- "为...提供了新的思路/视角"
- 过度使用"进行"（"进行研究"→"研究"）

### 4. 学术规范检查

- **逻辑连贯**：段落间是否有清晰的因果/对比/递进关系
- **表述精确**：模糊表达（"很多"、"一些"、"significantly"）替换为具体数据
- **被动语态适度**：科技写作允许被动，但不应全文被动
- **术语一致**：同一概念全文统一用词
- **时态正确**：方法/结果用过去时，普遍结论用现在时

### 5. 输出

- 直接给出润色后的文本
- 标注主要修改点（如用户要求）
- 如果是文件，保存润色版本到同目录（如 `introduction-polished.md`）

## 原则

- **保留作者的学术判断**：只改表达方式，不改观点和论证逻辑
- **最小修改**：能改一个词解决的不改整句
- **保持个人风格**：如果原文有作者自己的表达习惯且不影响清晰度，保留
- **不加内容**：润色不是扩写，不添加原文没有的论点或引用

## 示例

用户说："帮我把这段 Introduction 润色一下，去掉 AI 味"
→ 检测 AI 模式，替换为自然的学术表达

用户说："我有一篇 JFM 的范文，帮我按这个风格改写我的 Discussion"
→ 分析 JFM 范文风格，据此润色 Discussion

用户说："帮我把这段中文翻译成学术英语"
→ 翻译并润色，确保符合英文学术写作规范

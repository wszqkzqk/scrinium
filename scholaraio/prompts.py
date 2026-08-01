"""
prompts.py — 全库 LLM prompt 统一注册表 + JSON 解析
====================================================

所有发给 LLM 的 prompt 模板必须在此模块注册（见 ``PROMPTS``），
call site 通过 ``PROMPTS["<name>"].render(...)`` 或本模块的构建函数取用。

约定（新增 / 修改 prompt 时遵守）：
- 修改任何 prompt 模板必须同步在 CHANGELOG 中记录（prompt 是影响
  LLM 行为的外部契约，漂移需要可审计）。
- JSON 输出的 prompt 统一要求 "Return JSON only, no fencing"，
  响应一律用 :func:`parse_llm_json` 解析（围栏 / 裸 JSON / LaTeX
  反斜杠均兼容）。
- ``Prompt.name`` 与 metrics 的 purpose 对齐（如 ``"extract.robust"``）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Prompt:
    """一条注册在案的 LLM prompt 模板。

    Attributes:
        name: 注册名，与 metrics purpose 对齐（如 ``"extract.robust"``）。
        template: ``str.format`` 模板；字面花括号须写作 ``{{`` / ``}}``。
        json_mode: 调用时是否启用 JSON 响应格式（对应 ``call_llm`` 的
            ``json_mode``；``False`` 表示自由文本协议，如 NO_ABSTRACT 哨兵）。
        max_input: 输入截断上限（字符数），``None`` 表示不按字符截断。
        max_tokens: 生成上限，``None`` 表示使用 ``call_llm`` 默认值。
    """

    name: str
    template: str
    json_mode: bool = True
    max_input: int | None = None
    max_tokens: int | None = None

    def render(self, **kwargs) -> str:
        """Render the template with the given placeholders."""
        return self.template.format(**kwargs)


# ============================================================================
#  Metadata extraction (extract.llm / extract.robust)
#
#  The two extractor prompts share a common base (JSON schema fields and the
#  trailing rules block); each mode adds its own increment on top. Keep the
#  composition byte-identical to the rendered text — prompts are external
#  contracts, only the deduplication may change.
# ============================================================================

# Shared JSON schema fields (everything after the mode-specific title line)
_EXTRACT_SCHEMA_TAIL = """\
  "authors": ["姓名1", "姓名2", ...],
  "year": 2024,
  "doi": "10.xxx/xxx（不含 https://doi.org/，找不到填 null）",
  "journal": "期刊或会议名称，找不到填 null"
}}"""

# Shared trailing rules + content marker
_EXTRACT_RULES_TAIL = """\
- authors 找不到时填空列表 []
- year 必须是整数或 null
- 只返回 JSON，不要任何解释文字

--- 论文内容 ---
{header}"""

_EXTRACT_TEMPLATE_LLM = (
    "从以下学术论文页面提取元数据，以 JSON 格式返回，字段如下：\n"
    "{{\n"
    '  "title": "论文完整标题，找不到填 null",\n' + _EXTRACT_SCHEMA_TAIL + "\n\n" + "注意：\n"
    "- 期刊扫描页（如 Nature、Science）可能包含多篇文章片段。请识别有完整结构（标题 + 作者 + 正文）的主文章，忽略仅出现片段的其他文章\n"
    "- 如果文中出现多个 DOI（来自不同文章），说明 DOI 不可信，doi 字段填 null\n" + _EXTRACT_RULES_TAIL
)

_EXTRACT_TEMPLATE_ROBUST = (
    "以下是从一篇学术论文 PDF（经 OCR 转换为 markdown）中用正则提取的元数据，可能有 OCR 错误或缺失。\n"
    "请对照论文原文内容，校正并补全元数据，以 JSON 格式返回。\n\n"
    "正则提取结果：\n"
    "  title:   {regex_title}\n"
    "  authors: {regex_authors}\n"
    "  year:    {regex_year}\n"
    "  doi:     {regex_doi}\n"
    "  journal: {regex_journal}\n\n"
    "返回格式：\n"
    "{{\n"
    '  "title": "校正后的完整标题（修复 OCR 错误如连字、断字、乱码）",\n' + _EXTRACT_SCHEMA_TAIL + "\n\n" + "注意：\n"
    "- 优先信任论文原文，正则结果仅作参考\n"
    "- **学位论文处理**：如果检测到这是学位论文（博士/硕士论文、dissertation/thesis），请：\n"
    "  1. 根据正文主体（非封面/摘要）判断论文的主要写作语言\n"
    "  2. title 和 authors 使用主要语言版本（例如中文论文用中文标题和中文姓名，英文论文用英文）\n"
    "  3. 学位论文通常有中英文双封面，不要因为正则提取到了英文封面就用英文——以正文语言为准\n"
    "- **多篇文章识别**：期刊扫描页（如 Nature、Science）的 PDF 可能包含多篇文章的片段。\n"
    "  请根据以下标准识别主文章：找到有完整结构（标题 + 作者 + 正文主体 + 结论/参考文献）的研究论文，\n"
    "  忽略仅出现了尾部/参考文献/摘要片段的其他文章\n"
    "- 忽略期刊栏目标题（如 PERSPECTIVES, EDITORIAL, NEWS, COMMENTARY, LETTERS, REVIEW 等），这些不是论文标题\n"
    "- **PDF 解析错误修复**：输入的 markdown 由 PDF 解析器自动生成，可能存在以下问题，请结合上下文修正：\n"
    "  - OCR 字符错误：ln→In, rn→m, l→I, 0→O 等\n"
    "  - 标题/作者被截断或断行（尤其是封面页表格中的长标题，可能被拆成多行导致不完整）\n"
    "  - 连字/断字未合并\n"
    "  - 标题截断是常见问题：封面上的标题可能只有前半句。请务必与正文中出现的完整标题交叉验证（如摘要、引言首段、页眉等处），确保返回的是完整标题\n"
    + _EXTRACT_RULES_TAIL
)

# ============================================================================
#  Document-type detection (detect_thesis / detect_book)
# ============================================================================

# Single template shared by all detect kinds; per-kind wording comes from
# DETECT_TYPE_PARAMS. Keep the boolean JSON key first: max_tokens is only
# 200, so the verdict must survive truncation.
_DETECT_TYPE_TEMPLATE = (
    "Analyze the following document excerpt and determine if it is a {kind_desc}. "
    "Look for indicators such as: {indicators}.\n\n"
    'Respond in JSON: {{"{json_key}": true/false, "reason": "brief explanation"}}\n\n'
    "--- DOCUMENT START ---\n{text}\n--- DOCUMENT END ---"
)

DETECT_TYPE_PARAMS: dict[str, dict[str, str]] = {
    "thesis": {
        "kind_desc": "thesis or dissertation (学位论文/硕士论文/博士论文/毕业论文)",
        "indicators": (
            "degree awarding institution, advisor/supervisor, thesis committee, "
            "degree type (PhD/Master/Bachelor), declaration of originality, "
            "or thesis-specific formatting"
        ),
        "json_key": "is_thesis",
    },
    "book": {
        "kind_desc": "book or monograph (书籍/专著/教材/手册)",
        "indicators": (
            "ISBN, publisher information, table of contents with chapters, "
            "preface/foreword, book-specific formatting (parts/chapters rather "
            "than sections), or multiple self-contained chapters with distinct topics"
        ),
        "json_key": "is_book",
    },
}


def render_detect_prompt(kind: str, text: str) -> str:
    """Render the detect prompt for ``kind`` (``"thesis"`` / ``"book"``)."""
    params = DETECT_TYPE_PARAMS[kind]
    return PROMPTS[f"detect_{kind}"].render(text=text, **params)


# ============================================================================
#  Non-paper document metadata generation (doc_extract)
# ============================================================================

_DOC_EXTRACT_TEMPLATE = (
    "You are analyzing a document (not necessarily an academic paper). "
    "It could be a technical report, lecture notes, manual, standard, "
    "book chapter, or any other type of document.\n\n"
    "Your tasks:\n{task_str}\n\n"
    "Also extract if present:\n"
    "- **authors**: list of author/editor names\n"
    "- **year**: publication/creation year\n"
    "- **document_type**: one of: technical-report, lecture-notes, "
    "standard, book-chapter, manual, white-paper, presentation, "
    "meeting-notes, or document (generic fallback)\n\n"
    "{existing_title}"
    "Return JSON only, no fencing:\n"
    "{{\n"
    '  "title": "...",\n'
    '  "summary": "...",\n'
    '  "authors": ["..."],\n'
    '  "year": 2024,\n'
    '  "document_type": "..."\n'
    "}}\n\n"
    "--- DOCUMENT CONTENT ---\n\n"
    "{text}"
)


def build_doc_extract_prompt(text: str, *, has_title: bool, has_abstract: bool, existing_title: str = "") -> str:
    """Build LLM prompt for document metadata extraction."""
    tasks = []
    if not has_title:
        tasks.append("1. Generate a concise, descriptive **title** for this document")
    if not has_abstract:
        idx = "2" if not has_title else "1"
        tasks.append(
            f"{idx}. Write a **summary** (150-300 words) "
            "that captures the main content, key points, and purpose of "
            "this document. This summary will be used as the document's "
            "abstract for search indexing."
        )

    return PROMPTS["doc_extract"].render(
        task_str="\n".join(tasks),
        existing_title=f"Existing title: {existing_title}\n" if existing_title else "",
        text=text,
    )


# ============================================================================
#  Abstract extraction / verification (abstract.extract / abstract.verify)
# ============================================================================

_ABSTRACT_EXTRACT_TEMPLATE = (
    "Below is the beginning of an academic paper in markdown format. "
    "Extract the abstract/summary of the paper. "
    "Return ONLY the abstract text, nothing else. "
    "If there is no abstract in the text, return exactly: NO_ABSTRACT\n\n"
    "---\n{text}\n---"
)

_ABSTRACT_VERIFY_TEMPLATE = (
    "Below is an academic paper's markdown header, followed by an abstract "
    "that was extracted by regex. Check if this is a correct abstract.\n\n"
    "If it IS a valid abstract, return it as-is (clean up any obvious OCR "
    "artifacts or formatting issues if needed).\n"
    "If it is NOT a valid abstract (e.g., it's an address, keywords, funding "
    "info, or other non-abstract text), extract the real abstract from the "
    "markdown and return it.\n"
    "If there is no abstract at all, return exactly: NO_ABSTRACT\n\n"
    "Return ONLY the abstract text, nothing else.\n\n"
    "--- MARKDOWN ---\n{markdown}\n\n"
    "--- REGEX RESULT ---\n{regex_result}\n---"
)

# ============================================================================
#  Loader prompts (TOC denoise + L3 conclusion extraction)
# ============================================================================

_LOADER_TOC_TEMPLATE = (
    "The following are ALL lines starting with '#' extracted from an academic paper "
    "markdown file (converted from PDF by MinerU). Some are real section headers; "
    "others are NOISE to discard: author running headers (e.g. '# Smith and others'), "
    "journal name headers (e.g. '# Journal of Fluid Mechanics'), repeated paper titles, "
    "or publisher metadata (e.g. '# ARTICLEINFO', '# AFFILIATIONS', '# Articles You May Be Interested In').\n\n"
    "KEEP the following as real headers (they are needed as section boundary markers):\n"
    "- Numbered/lettered sections and subsections\n"
    "- Introduction, Abstract, Conclusion, Conclusions, Concluding Remarks, Summary\n"
    "- References, Bibliography\n"
    "- Appendix (any variant)\n"
    "- Post-matter sections: Acknowledgments, Acknowledgements, Funding, "
    "CRediT authorship contribution statement, Declaration of competing interest, "
    "Conflict of interest, Data availability, Author contributions, Author ORCIDs, "
    "Declaration of interests\n\n"
    "Assign level: 1=top-level, 2=subsection (e.g. '2.1'), 3=sub-subsection (e.g. '2.1.1').\n\n"
    "Headers:\n{headers}\n\nReturn JSON only:\n"
    '{{"toc": [{{"line": <N>, "level": <1|2|3>, "title": "<title>"}}, ...]}}'
)

_LOADER_L3_PRIMARY_TEMPLATE = (
    "Below are all section headers (with line numbers) from an academic paper markdown file.\n"
    "Identify the header that marks the START of the conclusion section "
    "(may be named 'Conclusion', 'Conclusions', 'Concluding Remarks', 'Summary', etc.).\n\n"
    "{headers}\n\n"
    'Return JSON only: {{"line": <line_number>, "header": "<header_text>"}}\n'
    'If no conclusion section exists, return: {{"line": null, "header": null}}'
)

_LOADER_L3_FALLBACK_TEMPLATE = (
    "Find the conclusion section in this academic paper (markdown format). "
    "Return the 1-indexed line number where the conclusion STARTS and where it ENDS "
    "(last line before References/Appendix/end of file).\n\n"
    "{sample}\n\n"
    'Return JSON only: {{"start_line": <N>, "end_line": <N>}}\n'
    'If no conclusion exists, return: {{"start_line": null, "end_line": null}}'
)

_LOADER_L3_VALIDATE_TEMPLATE = (
    "The following text was extracted as the conclusion section of an academic paper. "
    "Your tasks:\n"
    "1. Check if it contains actual conclusion content (summary of findings, contributions, or future work).\n"
    "2. If yes, return a CLEANED version:\n"
    "   - Remove the section header line (e.g. '# 6. Conclusion', '# Concluding Remarks')\n"
    "   - Remove any in-text running headers (e.g. '# Author and others', '# Journal Name')\n"
    "   - Remove everything AFTER the conclusion ends: Acknowledgments, Funding statements, "
    "CRediT authorship statements, Declaration of interests/competing interest, "
    "Data availability, Author ORCIDs, Author contributions, conflict of interest, etc.\n"
    "   - Keep only the actual conclusion/summary paragraphs. Do NOT truncate mid-sentence.\n"
    "3. If it contains NO conclusion content at all, set conclusion to null.\n\n"
    "{text}\n\n"
    'Return JSON only: {{"conclusion": "<cleaned text or null>", "reason": "<one sentence>"}}'
)

# ============================================================================
#  Translation (translate)
# ============================================================================

# Terminology annotation rules per target language
TRANSLATE_TERMINOLOGY_RULES: dict[str, str] = {
    "zh": "- 对于专业术语，在首次出现时用「英文 (中文翻译)」格式",
    "ja": "- 専門用語は初出時に「英語 (日本語訳)」の形式で記載すること",
    "ko": "- 전문 용어는 처음 등장할 때 「영어 (한국어 번역)」 형식을 사용",
}

_TRANSLATE_TEMPLATE = """\
翻译以下学术论文段落至{target_lang}。

重要事项：
- 保留所有 markdown 格式（#, **, ``, [links]、表格等）
- 保留 LaTeX 公式（$...$, $$...$$）不翻译
- 保留代码块（```...```）不翻译
- 保留图片引用（![...](...)）不翻译
- 保留作者姓名和引用格式（如 [Smith et al., 2023]）
{rule}- 只返回翻译文本，不要任何解释

原文：
{text}"""


def build_translate_prompt(text: str, target_lang: str, lang_name: str) -> str:
    """Build the translation prompt with language-appropriate terminology rule."""
    rule = TRANSLATE_TERMINOLOGY_RULES.get(target_lang)
    return PROMPTS["translate"].render(
        target_lang=lang_name,
        rule=f"{rule}\n" if rule else "",
        text=text,
    )


# ============================================================================
#  Registry
# ============================================================================

PROMPTS: dict[str, Prompt] = {
    p.name: p
    for p in (
        Prompt("extract.llm", _EXTRACT_TEMPLATE_LLM, max_input=50_000),
        Prompt("extract.robust", _EXTRACT_TEMPLATE_ROBUST, max_input=50_000),
        Prompt("detect_thesis", _DETECT_TYPE_TEMPLATE, max_input=30_000, max_tokens=200),
        Prompt("detect_book", _DETECT_TYPE_TEMPLATE, max_input=30_000, max_tokens=200),
        Prompt("doc_extract", _DOC_EXTRACT_TEMPLATE, max_input=60_000, max_tokens=1000),
        Prompt("abstract.extract", _ABSTRACT_EXTRACT_TEMPLATE, json_mode=False, max_input=3_000, max_tokens=1000),
        Prompt("abstract.verify", _ABSTRACT_VERIFY_TEMPLATE, json_mode=False, max_input=3_000, max_tokens=1000),
        Prompt("loader.toc", _LOADER_TOC_TEMPLATE),
        Prompt("loader.l3_primary", _LOADER_L3_PRIMARY_TEMPLATE),
        Prompt("loader.l3_fallback", _LOADER_L3_FALLBACK_TEMPLATE),
        Prompt("loader.l3_validate", _LOADER_L3_VALIDATE_TEMPLATE),
        Prompt("translate", _TRANSLATE_TEMPLATE, json_mode=False),
    )
}


# ============================================================================
#  Unified LLM JSON response parsing
# ============================================================================

# Fix unescaped backslashes (e.g. LaTeX: \alpha, \vec, \frac) while
# preserving valid JSON escapes: \" \\ \/ \b \f \n \r \t \uXXXX
_LATEX_BACKSLASH_RE = re.compile(r'\\(?!["\\/bfnrtu])')

_FENCED_BLOCK_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)
_BARE_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _try_parse_dict(text: str) -> dict | None:
    """Parse ``text`` as a JSON object, with a LaTeX backslash fix-up pass."""
    for candidate in (text, _LATEX_BACKSLASH_RE.sub(r"\\\\", text)):
        try:
            result = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict):
            return result
    return None


def parse_llm_json(text: str) -> dict | None:
    """Tolerant JSON-object extraction from an LLM response.

    Superset of the historically divergent in-module parsers:

    1. ```json fenced block (anywhere in the response)
    2. Whole response after stripping surrounding fences
    3. First bare ``{...}`` object (greedy, tolerates surrounding prose)

    Each candidate also gets a LaTeX backslash fix-up pass. Non-object JSON
    (arrays, scalars) is not accepted.

    Returns:
        Parsed ``dict``, or ``None`` when nothing parses — callers map
        ``None`` onto their existing degradation path (``or {}``, raise,
        or fall back to regex results).
    """
    if not text:
        return None
    text = text.strip()
    if not text:
        return None

    # 1. Fenced block
    m = _FENCED_BLOCK_RE.search(text)
    if m:
        result = _try_parse_dict(m.group(1))
        if result is not None:
            return result

    # 2. Whole response with surrounding fences stripped
    stripped = re.sub(r"^```\w*\s*", "", text)
    stripped = re.sub(r"\s*```$", "", stripped)
    result = _try_parse_dict(stripped)
    if result is not None:
        return result

    # 3. Bare JSON object embedded in prose
    m = _BARE_OBJECT_RE.search(text)
    if m:
        return _try_parse_dict(m.group(0))

    return None

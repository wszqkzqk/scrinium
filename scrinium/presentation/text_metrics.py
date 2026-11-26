"""CJK-aware text layout estimation for PowerPoint shapes and style components.

Provides deterministic width/line-wrap/height estimates for mixed Chinese and
Latin text so build-time components (`card`, `text`, `base_slide`) and the
document inspector share the same overflow rules.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Safety factor for font metric differences across YaHei / PingFang / Noto CJK.
_WIDTH_SAFETY = 1.04
# PowerPoint single-line height (line_spacing=1.0) for mixed CJK/Latin runs.
_SINGLE_LINE_EM = 1.24

_NARROW_ASCII = set("iIlj.,:;|'!()[]{}` ")
_WIDE_ASCII = set("MWmw@%&")
_NO_BREAK_BEFORE = set("，。；：？！、）】》」』’”%,.;:!?)]}")
_NO_BREAK_AFTER = set("（【《「『‘“([{")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_./:+\-–—=<>\[\]()]+|\s+|.", re.DOTALL)


def char_em_width(char: str, bold: bool = False) -> float:
    """Approximate glyph advance width in em units."""
    if char == "\t":
        return 1.12
    if char == " ":
        return 0.30
    eaw = unicodedata.east_asian_width(char)
    if eaw in ("W", "F"):
        return 1.0
    if char in _NARROW_ASCII:
        return 0.32 if bold else 0.29
    if char in _WIDE_ASCII:
        return 0.88 if bold else 0.82
    if char.isupper() or char.isdigit():
        return 0.67 if bold else 0.62
    return (0.58 if bold else 0.53) * _WIDTH_SAFETY


def text_width_in(content: str, font_pt: float, bold: bool = False) -> float:
    """Estimate single-line width in inches."""
    em = sum(char_em_width(ch, bold) for ch in content)
    return em * (font_pt / 72.0) * (_WIDTH_SAFETY if _has_wide_char(content) else 1.0)


def _has_wide_char(content: str) -> bool:
    return any(unicodedata.east_asian_width(ch) in ("W", "F") for ch in content)


def _tokenize(line: str) -> list[str]:
    return _TOKEN_RE.findall(line)


def wrap_paragraph(content: str, width_in: float, font_pt: float, bold: bool = False) -> list[str]:
    """Greedy CJK/Latin word-aware line wrapping within ``width_in``."""
    if not content:
        return [""]
    avail = max(width_in, 0.05)
    tokens = _tokenize(content)
    lines: list[str] = []
    current = ""
    current_w = 0.0

    def token_w(tok: str) -> float:
        return text_width_in(tok, font_pt, bold)

    for tok in tokens:
        if tok.isspace():
            if not current:
                continue
            tok = " "
        tw = token_w(tok)
        if current and current_w + tw > avail and tok != " ":
            # Avoid leaving closing punctuation at the start of a new line when possible.
            if len(tok) == 1 and tok in _NO_BREAK_BEFORE and current_w + tw <= avail * 1.06:
                current += tok
                lines.append(current)
                current = ""
                current_w = 0.0
                continue
            if current[-1] in _NO_BREAK_AFTER and len(current) > 1:
                carry = current[-1]
                lines.append(current[:-1])
                current = carry
                current_w = token_w(carry)
            else:
                lines.append(current.rstrip(" "))
                current = ""
                current_w = 0.0

        if tw > avail:
            # Long unbroken token (e.g., URL): split by character.
            for ch in tok:
                cw = token_w(ch)
                if current and current_w + cw > avail:
                    lines.append(current.rstrip(" "))
                    current = ch
                    current_w = cw
                else:
                    current += ch
                    current_w += cw
        else:
            current += tok
            current_w += tw

    if current or not lines:
        lines.append(current.rstrip(" "))
    return lines


@dataclass
class ParagraphSpec:
    text: str
    font_pt: float = 18.0
    bold: bool = False
    line_spacing: float = 1.0
    space_before_pt: float = 0.0
    space_after_pt: float = 0.0


@dataclass
class TextFit:
    available_width_in: float
    available_height_in: float
    needed_height_in: float
    wrapped_lines: list[list[str]] = field(default_factory=list)

    @property
    def total_lines(self) -> int:
        return sum(len(lines) for lines in self.wrapped_lines)

    @property
    def overflows(self) -> bool:
        return self.needed_height_in > self.available_height_in + 0.03


def measure_paragraphs(
    paragraphs: list[ParagraphSpec],
    width_in: float,
    height_in: float,
    margin_lr_in: float = 0.0,
    margin_tb_in: float = 0.0,
) -> TextFit:
    """Measure wrapped height of paragraphs inside a text box or table cell."""
    avail_w = max(0.05, width_in - 2.0 * margin_lr_in)
    avail_h = max(0.0, height_in - 2.0 * margin_tb_in)
    needed = 0.0
    wrapped: list[list[str]] = []
    for idx, spec in enumerate(paragraphs):
        font_pt = spec.font_pt or 18.0
        lines = wrap_paragraph(spec.text, avail_w, font_pt, spec.bold) if spec.text else [""]
        wrapped.append(lines)
        mult = spec.line_spacing if spec.line_spacing and spec.line_spacing > 0 else 1.0
        line_h_in = (_SINGLE_LINE_EM * font_pt * mult) / 72.0
        para_h = len(lines) * line_h_in
        if idx > 0:
            para_h += max(0.0, spec.space_before_pt) / 72.0
        para_h += max(0.0, spec.space_after_pt) / 72.0
        needed += para_h
    return TextFit(
        available_width_in=avail_w,
        available_height_in=avail_h,
        needed_height_in=needed,
        wrapped_lines=wrapped,
    )

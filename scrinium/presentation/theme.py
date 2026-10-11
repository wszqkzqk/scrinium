from dataclasses import dataclass, replace
from pathlib import Path

from pptx.dml.color import RGBColor


@dataclass(frozen=True)
class Theme:
    font_cn: str
    font_en: str
    accent: RGBColor
    footer_text: str
    logo_dark: Path | None
    logo_red: Path | None
    logo_white: Path | None


DEFAULT_THEME = Theme(
    font_cn="Microsoft YaHei",
    font_en="Arial",
    accent=RGBColor(39, 43, 48),
    footer_text="",
    logo_dark=None,
    logo_red=None,
    logo_white=None,
)

__all__ = ["DEFAULT_THEME", "Theme", "replace"]

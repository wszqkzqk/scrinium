from pathlib import Path

from scrinium.presentation.pptx_style import (
    DARK,
    MID,
    WHITE,
    base_slide,
    configure_theme,
    new_presentation,
    rect,
    set_theme_east_asian_font,
    text,
)
from scrinium.presentation.theme import DEFAULT_THEME

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "starter.pptx"


def cover(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    rect(slide, 0, 0, 13.333, 7.5, WHITE)
    rect(slide, 0, 0, 0.18, 7.5, DEFAULT_THEME.accent)
    text(slide, "Presentation", 0.85, 2.35, 11.5, 0.75, 38, DARK, True)
    text(slide, "Starter presentation", 0.87, 3.30, 10.0, 0.40, 20, MID)


def content(prs):
    slide = base_slide(prs, "Slide title", "01  Section", 2)
    text(slide, "Replace this text with your content.", 0.85, 2.0, 11.5, 0.5, 22, MID)


def slide_builders():
    return [cover, content]


def build():
    configure_theme(DEFAULT_THEME)
    prs = new_presentation()
    for builder in slide_builders():
        builder(prs)
    prs.save(OUT)
    set_theme_east_asian_font(OUT, DEFAULT_THEME.font_cn, DEFAULT_THEME.font_en)
    print(OUT)


if __name__ == "__main__":
    build()

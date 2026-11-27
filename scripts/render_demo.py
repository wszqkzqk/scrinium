"""Render docs/assets/scrinium-demo.gif from real CLI runs on an isolated fixture library.

Usage:
    .venv/bin/python scripts/render_demo.py [output.gif]

Uses a temporary synthetic library of generic physics/engineering papers so no
user library data is touched or exposed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT_DEFAULT = ROOT / "docs" / "assets" / "scrinium-demo.gif"

WIDTH, HEIGHT = 960, 560
PAD_X, PAD_Y = 24, 64
LINE_H = 20
MAX_ROWS = (HEIGHT - PAD_Y - 20) // LINE_H
MAX_COLS = 96
FPS = 24

BG = (13, 17, 23)
BAR = (30, 36, 46)
FG = (230, 237, 243)
MUTED = (145, 158, 171)
PROMPT = (126, 231, 135)
ACCENT = (121, 192, 255)
WARN_OK = (126, 231, 135)


def _load_font(size: int = 15) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "C:/Windows/Fonts/consola.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default(size=size)


def _seed_library(root: Path) -> dict[str, str]:
    papers_dir = root / "data" / "papers"
    papers_dir.mkdir(parents=True)
    base_refs = [
        {"doi": "10.1063/1.1699114"},
        {"doi": "10.1103/PhysRev.140.A1133"},
    ]
    specs = [
        (
            "Smith-2023-Turbulence-Modeling",
            "Turbulence modeling in boundary layers",
            "Smith J.",
            2023,
            "Journal of Fluid Mechanics",
            "10.1234/jfm.2023.001",
            ["fluid-dynamics", "turbulence"],
            128,
            base_refs,
        ),
        (
            "Lee-2021-Channel-Flow-Simulation",
            "Large-eddy simulation of turbulent channel flow",
            "Lee A.",
            2021,
            "Physics of Fluids",
            "10.1234/pof.2021.042",
            ["fluid-dynamics", "turbulence"],
            86,
            [*base_refs, {"doi": "10.1234/jfm.2023.001"}],
        ),
        (
            "Garcia-2020-Heat-Transfer-Pipes",
            "Convective heat transfer in turbulent pipe flow",
            "Garcia M.",
            2020,
            "International Journal of Heat and Mass Transfer",
            "10.1234/ijhmt.2020.019",
            ["fluid-dynamics", "heat-transfer"],
            64,
            base_refs,
        ),
        (
            "Metropolis-1953-Monte-Carlo",
            "Equation of state calculations by fast computing machines",
            "Metropolis N.",
            1953,
            "Journal of Chemical Physics",
            "10.1063/1.1699114",
            ["monte-carlo"],
            42000,
            [],
        ),
        (
            "Kohn-1965-Density-Functional",
            "Self-consistent equations with exchange-correlation",
            "Kohn W.",
            1965,
            "Physical Review",
            "10.1103/PhysRev.140.A1133",
            ["quantum-chemistry"],
            38000,
            [],
        ),
    ]
    for dirname, title, author, year, journal, doi, tags, cites, refs in specs:
        d = papers_dir / dirname
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": dirname[:8].lower() + "-demo",
                    "title": title,
                    "authors": [author, "Doe J."],
                    "first_author_lastname": author.split()[0],
                    "year": year,
                    "journal": journal,
                    "doi": doi,
                    "tags": tags,
                    "references": refs,
                    "abstract": f"A computational study of {title.lower()} with turbulence benchmark validation.",
                    "l3_conclusion": "Matches reference benchmarks within 2% error while cutting runtime by 8x.",
                    "paper_type": "journal-article",
                    "citation_count": {"crossref": cites},
                }
            ),
            encoding="utf-8",
        )
        (d / "paper.md").write_text(
            f"# {title}\n\n## Introduction\n\nBenchmark study of boundary layer turbulence.\n",
            encoding="utf-8",
        )

    from pptx import Presentation

    prs = Presentation()
    for idx in range(12):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.shapes.add_textbox(914400, 914400, 4 * 914400, 914400).text = f"Slide {idx + 1}"
    prs.save(root / "report.pptx")

    cfg = root / "config.yaml"
    cfg.write_text("paths:\n  papers_dir: data/papers\n  index_db: data/index.db\n", encoding="utf-8")
    return {"SCRINIUM_CONFIG": str(cfg), "cwd": str(root)}


def _run_cli(args: list[str], ctx: dict[str, str]) -> list[str]:
    code = "import sys; from scrinium.cli import main; sys.argv = ['scrinium'] + sys.argv[1:]; main()"
    env = {**os.environ, "SCRINIUM_CONFIG": ctx["SCRINIUM_CONFIG"], "PYTHONPATH": str(ROOT)}
    proc = subprocess.run(
        [sys.executable, "-c", code, *args],
        cwd=ctx["cwd"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout + proc.stderr).rstrip("\n")
    lines: list[str] = []
    for ln in out.splitlines():
        if ln.startswith("Or run `scrinium workspace add"):
            continue
        if len(ln) <= MAX_COLS:
            lines.append(ln)
        else:
            lines.extend(textwrap.wrap(ln, width=MAX_COLS, subsequent_indent="      ", break_long_words=False))
    return lines


def _style_segments(line: str, is_prompt: bool = False):
    if is_prompt:
        return [("$ ", PROMPT), (line[2:], FG)]
    if line.startswith("$ "):
        return [("$ ", PROMPT), (line[2:], FG)]
    if line.startswith("Keyword search found") or line.startswith("Found "):
        return [(line, ACCENT)]
    if line.startswith("[") and "]" in line[:6]:
        head, rest = line.split("]", 1)
        return [(head + "]", ACCENT), (rest, FG)]
    if line.startswith("slides:") or line.startswith("--- Summary"):
        return [(line, WARN_OK)]
    if line.startswith("--- "):
        return [(line, ACCENT)]
    if ":" in line[:12] and line[:10].strip().isalpha():
        k, v = line.split(":", 1)
        return [(k + ":", MUTED), (v, FG)]
    return [(line, MUTED)]


def render(out_path: Path) -> None:
    font = _load_font(15)
    char_w = font.getlength("M")
    with tempfile.TemporaryDirectory(prefix="scrinium_demo_") as tmp:
        root = Path(tmp)
        ctx = _seed_library(root)
        _run_cli(["index"], ctx)

        script = [
            ("search turbulence --top 3", ["search", "turbulence", "--top", "3"]),
            (
                "show Smith-2023-Turbulence-Modeling --layer 3",
                ["show", "Smith-2023-Turbulence-Modeling", "--layer", "3"],
            ),
            (
                "snowball Smith-2023-Turbulence-Modeling --top 3",
                ["snowball", "Smith-2023-Turbulence-Modeling", "--top", "3"],
            ),
            ("document inspect report.pptx", ["document", "inspect", "report.pptx"]),
        ]

        # Build timeline of (visible_lines, cursor_col_or_None, hold_frames)
        timeline: list[tuple[list[tuple[str, bool]], int | None, int]] = []
        visible: list[tuple[str, bool]] = []
        for typed_cmd, cli_args in script:
            full_prompt = f"$ scrinium {typed_cmd}"
            for n in range(2, len(full_prompt) + 1, 2):
                timeline.append(([*visible, (full_prompt[:n], True)], n, 1))
            timeline.append(([*visible, (full_prompt, True)], len(full_prompt), 8))
            visible.append((full_prompt, True))

            out_lines = _run_cli(cli_args, ctx)
            # Keep inspect output compact: show the first 3 lines and the summary block
            if cli_args[0] == "document":
                summary_idx = next((i for i, l in enumerate(out_lines) if l.startswith("--- Summary")), len(out_lines))
                out_lines = [*out_lines[:3], "  ...", *out_lines[summary_idx:]]

            for start in range(0, len(out_lines), 3):
                chunk = out_lines[start : start + 3]
                visible.extend((l, False) for l in chunk)
                timeline.append((list(visible), None, 2))
            timeline.append((list(visible), None, 42))
            visible.append(("", False))

        timeline.append((list(visible), None, 72))

        frames: list[Image.Image] = []
        durations: list[int] = []
        frame_dt = round(1000 / FPS)
        base_palette_img: Image.Image | None = None

        for vis_lines, cursor_col, hold in timeline:
            shown = vis_lines[-MAX_ROWS:]
            img = Image.new("RGB", (WIDTH, HEIGHT), BG)
            draw = ImageDraw.Draw(img)
            # Top window bar
            draw.rounded_rectangle((0, 0, WIDTH - 1, HEIGHT - 1), radius=10, outline=(48, 54, 61), fill=BG)
            draw.rectangle((1, 1, WIDTH - 2, 40), fill=BAR)
            draw.line((1, 40, WIDTH - 2, 40), fill=(48, 54, 61))
            for cx, col in [(22, (255, 95, 86)), (42, (255, 189, 46)), (62, (39, 201, 63))]:
                draw.ellipse((cx - 6, 14, cx + 6, 26), fill=col)
            title = "scrinium — research workspace"
            draw.text(((WIDTH - draw.textlength(title, font=font)) / 2, 12), title, font=font, fill=MUTED)

            # Clip region for terminal text
            txt_layer = Image.new("RGB", (WIDTH - 2 * PAD_X, HEIGHT - PAD_Y), BG)
            tdraw = ImageDraw.Draw(txt_layer)
            y = 4
            for idx, (ln, is_p) in enumerate(shown):
                x = 0
                for seg, col in _style_segments(ln, is_p):
                    tdraw.text((x, y), seg, font=font, fill=col)
                    x += len(seg) * char_w
                if idx == len(shown) - 1 and cursor_col is not None:
                    cx = cursor_col * char_w
                    tdraw.rectangle((cx, y + 1, cx + char_w - 1, y + 17), fill=FG)
                y += LINE_H
            img.paste(txt_layer, (PAD_X, PAD_Y))

            if base_palette_img is None:
                base_palette_img = img.quantize(colors=64, method=Image.Quantize.MEDIANCUT)
                q = base_palette_img
            else:
                q = img.quantize(palette=base_palette_img, dither=Image.Dither.NONE)
            frames.append(q)
            durations.append(frame_dt * hold)

        # Coalesce identical consecutive frames into a single longer-duration frame
        uniq_frames: list[Image.Image] = []
        uniq_durations: list[int] = []
        for frame, dur in zip(frames, durations):
            if uniq_frames and frame.tobytes() == uniq_frames[-1].tobytes():
                uniq_durations[-1] += dur
            else:
                uniq_frames.append(frame)
                uniq_durations.append(dur)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        uniq_frames[0].save(
            out_path,
            save_all=True,
            append_images=uniq_frames[1:],
            duration=uniq_durations,
            loop=0,
            optimize=True,
        )
        print(f"Saved {out_path} ({len(frames)} frames, {out_path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DEFAULT
    render(target)

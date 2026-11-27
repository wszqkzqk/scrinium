"""Office document inspection tools (DOCX / PPTX / XLSX).

Provides structured text summaries of Office documents for AI agents
to verify layout, content, and detect common issues (overflow, missing
content, etc.) without opening a GUI application.
"""

from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger(__name__)

# EMU per inch constant (used by python-pptx)
_EMU_PER_INCH = 914400


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------


def inspect(path: Path, fmt: str | None = None) -> str:
    """Inspect an Office document and return a structured text summary.

    Args:
        path: Path to the Office file.
        fmt: File format override (``"docx"``, ``"pptx"``, ``"xlsx"``).
            Auto-detected from extension when *None*.

    Returns:
        Human-readable inspection report.

    Raises:
        ValueError: If the file format is unsupported or cannot be detected.
        FileNotFoundError: If *path* does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise ValueError(f"Path is not a file: {path}")

    if fmt is None:
        fmt = path.suffix.lstrip(".").lower()

    dispatch = {
        "pptx": inspect_pptx,
        "docx": inspect_docx,
        "xlsx": inspect_xlsx,
    }
    func = dispatch.get(fmt)
    if func is None:
        raise ValueError(f"Unsupported file format: .{fmt} (supported: docx / pptx / xlsx)")
    return func(path)


# ---------------------------------------------------------------------------
# PPTX inspection
# ---------------------------------------------------------------------------


def pos_text(shape) -> str:
    txt = shape.text.strip().replace("\n", " ") if getattr(shape, "has_text_frame", False) else ""
    return txt[:24]


def inspect_pptx(path: Path) -> str:
    """Inspect a PowerPoint file and return a structured text summary.

    Args:
        path: Path to the ``.pptx`` file.

    Returns:
        Slide-by-slide report with shape positions, sizes, text preview,
        image info, and CJK-aware overflow warnings.
    """
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
    except ImportError:
        raise ImportError("python-pptx is not installed; run: pip install scrinium[office]")

    from scrinium.presentation.text_metrics import ParagraphSpec, measure_paragraphs

    def _para_spec(para) -> ParagraphSpec:
        sizes = [r.font.size.pt for r in para.runs if r.font.size is not None]
        font_pt = max(sizes) if sizes else 18.0
        bold = any(bool(r.font.bold) for r in para.runs)
        ls = para.line_spacing if isinstance(para.line_spacing, (int, float)) else 1.0
        sb = para.space_before.pt if para.space_before is not None else 0.0
        sa = para.space_after.pt if para.space_after is not None else 0.0
        return ParagraphSpec(
            text=para.text,
            font_pt=font_pt,
            bold=bold,
            line_spacing=float(ls) if ls else 1.0,
            space_before_pt=sb,
            space_after_pt=sa,
        )

    def _measure_tf(tf, w_in: float, h_in: float):
        ml = (tf.margin_left or 0) / _EMU_PER_INCH
        mr = (tf.margin_right or 0) / _EMU_PER_INCH
        mt = (tf.margin_top or 0) / _EMU_PER_INCH
        mb = (tf.margin_bottom or 0) / _EMU_PER_INCH
        specs = [_para_spec(p) for p in tf.paragraphs]
        fit = measure_paragraphs(specs, w_in, h_in, margin_lr_in=(ml + mr) / 2.0, margin_tb_in=0.0)
        fit.needed_height_in += mt + mb
        fit.available_height_in = h_in
        return fit

    prs = Presentation(str(path))
    sw = (prs.slide_width or 0) / _EMU_PER_INCH
    sh = (prs.slide_height or 0) / _EMU_PER_INCH
    total = len(prs.slides)

    lines: list[str] = []
    lines.append(f"=== PPTX: {path.name} ===")
    lines.append(f'Slide size: {sw:.1f}" x {sh:.1f}" ({total} slides)')
    lines.append("")
    total_warnings = 0

    for i, slide in enumerate(prs.slides, 1):
        layout_name = slide.slide_layout.name
        lines.append(f"--- Slide {i}/{total} (layout: {layout_name}) ---")

        warnings: list[str] = []
        shapes_list = list(slide.shapes)
        bg_rects: list[tuple[float, float, float, float]] = []
        for bg in shapes_list:
            if bg.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE and bg.width and bg.height:
                bw = bg.width / _EMU_PER_INCH
                bh = bg.height / _EMU_PER_INCH
                if bw < sw - 0.5 and bh > 0.3:
                    bg_rects.append(((bg.left or 0) / _EMU_PER_INCH, (bg.top or 0) / _EMU_PER_INCH, bw, bh))

        for shape in shapes_list:
            left = shape.left / _EMU_PER_INCH if shape.left else 0
            top = shape.top / _EMU_PER_INCH if shape.top else 0
            w = shape.width / _EMU_PER_INCH if shape.width else 0
            h = shape.height / _EMU_PER_INCH if shape.height else 0
            right = left + w
            bottom = top + h

            if right > sw + 0.05:
                warnings.append(
                    f'  \u26a0 Overflow: shape right edge {right:.2f}" > slide width {sw:.1f}" ({pos_text(shape)})'
                )
            if bottom > sh + 0.05:
                warnings.append(
                    f'  \u26a0 Overflow: shape bottom edge {bottom:.2f}" > slide height {sh:.1f}" ({pos_text(shape)})'
                )

            pos = f'({left:.2f}",{top:.2f}") {w:.2f}"x{h:.2f}"'

            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    img = shape.image
                    size_kb = len(img.blob) // 1024
                    lines.append(f"  [Image] {pos}  [{img.content_type}, {size_kb}KB]")
                except Exception:
                    lines.append(f"  [Image] {pos}")
                continue

            if shape.has_table:
                tbl = shape.table
                nr = len(tbl.rows)
                nc = len(tbl.columns)
                header_cells = [tbl.cell(0, c).text[:20] for c in range(min(nc, 5))]
                hdr_str = " | ".join(header_cells)
                if nc > 5:
                    hdr_str += " | ..."
                lines.append(f"  [Table {nr}x{nc}] {pos}")
                lines.append(f"    Header: {hdr_str}")
                required_h = 0.0
                for r_idx, row in enumerate(tbl.rows):
                    row_h = (row.height or 0) / _EMU_PER_INCH
                    row_need = 0.0
                    for c_idx in range(nc):
                        cell = tbl.cell(r_idx, c_idx)
                        cw = (tbl.columns[c_idx].width or 0) / _EMU_PER_INCH
                        if not cell.text.strip():
                            row_need = max(row_need, 0.22)
                            continue
                        c_fit = _measure_tf(cell.text_frame, cw, row_h)
                        row_need = max(row_need, c_fit.needed_height_in)
                        if c_fit.overflows:
                            warnings.append(
                                f"  \u26a0 Table cell ({r_idx + 1},{c_idx + 1}) text may overflow: "
                                f'needs {c_fit.needed_height_in:.2f}" > row height {row_h:.2f}" ("{cell.text[:24]}")'
                            )
                    required_h += max(row_h, row_need)
                if required_h > h + 0.06:
                    warnings.append(
                        f'  \u26a0 Table rendered height ~{required_h:.2f}" > declared height {h:.2f}"; '
                        f'bottom edge will extend to {top + required_h:.2f}"'
                    )
                continue

            if shape.has_text_frame:
                tf = shape.text_frame
                paras = [p.text.strip() for p in tf.paragraphs if p.text.strip()]
                if not paras:
                    continue

                label = "TextBox"
                try:
                    if shape.placeholder_format is not None:
                        idx = shape.placeholder_format.idx
                        label = f"Placeholder {idx}"
                except ValueError:
                    pass

                lines.append(f"  [{label}] {pos}")
                for p_text in paras[:3]:
                    display = p_text[:60] + ("..." if len(p_text) > 60 else "")
                    lines.append(f'    "{display}"')
                if len(paras) > 3:
                    lines.append(f"    ... (+{len(paras) - 3} more)")

                first_para = tf.paragraphs[0]
                if first_para.runs:
                    run = first_para.runs[0]
                    font_info = []
                    if run.font.size:
                        font_info.append(f"{run.font.size.pt:.0f}pt")
                    if run.font.bold:
                        font_info.append("bold")
                    if run.font.italic:
                        font_info.append("italic")
                    if font_info:
                        lines.append(f"    font: {', '.join(font_info)}")

                fit = _measure_tf(tf, w, h)
                valign = tf.vertical_anchor
                est_top = top
                if valign is not None and int(valign) == 3:  # MSO_ANCHOR.MIDDLE
                    est_top = top + max(0.0, (h - fit.needed_height_in) / 2.0)
                elif valign is not None and int(valign) == 4:  # MSO_ANCHOR.BOTTOM
                    est_top = top + max(0.0, h - fit.needed_height_in)
                est_bottom = est_top + fit.needed_height_in

                if fit.overflows:
                    warnings.append(
                        f"  \u26a0 Text may overflow {pos}: {fit.total_lines} wrapped line(s) need "
                        f'{fit.needed_height_in:.2f}" > box height {h:.2f}" ("{paras[0][:28]}")'
                    )

                for bx, by, bw, bh in bg_rects:
                    if (bx, by, bw, bh) == (left, top, w, h):
                        continue
                    if bx <= left + 0.02 and by <= top + 0.02 and left + w <= bx + bw + 0.05 and top < by + bh - 0.05:
                        card_bottom = by + bh
                        if est_bottom > card_bottom + 0.02:
                            warnings.append(
                                f'  \u26a0 Text extends past enclosing card bottom: estimated text bottom {est_bottom:.2f}" > '
                                f'card bottom {card_bottom:.2f}" ("{paras[0][:28]}")'
                            )
                        break

        if warnings:
            total_warnings += len(warnings)
            lines.extend(warnings)

        lines.append("")

    img_count = sum(1 for slide in prs.slides for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE)
    tbl_count = sum(1 for slide in prs.slides for s in slide.shapes if s.has_table)
    lines.append("--- Summary ---")
    lines.append(f"slides: {total} | images: {img_count} | tables: {tbl_count} | layout warnings: {total_warnings}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DOCX inspection
# ---------------------------------------------------------------------------


def inspect_docx(path: Path) -> str:
    """Inspect a Word document and return a structured text summary.

    Args:
        path: Path to the ``.docx`` file.

    Returns:
        Document structure report with headings, paragraphs, tables,
        images, and style info.
    """
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError:
        raise ImportError("python-docx is not installed; run: pip install scrinium[office]")

    doc = Document(str(path))

    lines: list[str] = []
    lines.append(f"=== DOCX: {path.name} ===")

    # Section info
    for si, section in enumerate(doc.sections):
        pw = section.page_width.inches if section.page_width else 0
        ph = section.page_height.inches if section.page_height else 0
        orient = "landscape" if pw > ph else "portrait"
        lines.append(f'  Section {si + 1}: {pw:.1f}" x {ph:.1f}" ({orient})')

    # Count elements and collect styles
    styles_used: set[str] = set()
    h_counts: dict[str, int] = {}
    para_count = 0
    table_count = 0
    image_count = 0

    lines.append("")
    lines.append("--- Document structure ---")

    # Walk document body in order (block-level) to avoid paragraph/table desync.
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            para = Paragraph(child, doc)

            style_name = para.style.name if para.style else "Normal"
            styles_used.add(style_name)
            text = para.text.strip()

            # Check for images in this paragraph
            drawings = child.findall(f".//{qn('w:drawing')}")
            if drawings:
                image_count += len(drawings)
                for _ in drawings:
                    lines.append("  [Image] (embedded image)")

            if style_name.startswith("Heading"):
                level = style_name.replace("Heading ", "H")
                h_counts[level] = h_counts.get(level, 0) + 1
                display = text[:70] + ("..." if len(text) > 70 else "")
                lines.append(f'  [{style_name}] "{display}"')
            elif style_name.startswith("List"):
                # Emit each list paragraph as one list-item line.
                lines.append(f'  [{style_name}] "{text[:60]}"')
                para_count += 1
            elif "toc" in style_name.lower():
                if para_count == 0 or not lines[-1].startswith("  [TOC"):
                    lines.append("  [TOC] (TOC field)")
                para_count += 1
            elif text:
                para_count += 1
                display = text[:70] + ("..." if len(text) > 70 else "")
                # Font info
                font_info = ""
                if para.runs:
                    run = para.runs[0]
                    parts = []
                    if run.font.name:
                        parts.append(run.font.name)
                    if run.font.size:
                        parts.append(f"{run.font.size.pt:.0f}pt")
                    if run.bold:
                        parts.append("bold")
                    if parts:
                        font_info = f" [{', '.join(parts)}]"
                lines.append(f'  [Paragraph] "{display}"{font_info}')
            else:
                # Empty paragraph (spacer)
                para_count += 1

        elif child.tag == qn("w:tbl"):
            table = Table(child, doc)
            table_count += 1

            nr = len(table.rows)
            nc = len(table.columns)
            style = table.style.name if table.style else "?"
            lines.append(f"  [Table {nr}x{nc}] (style: {style})")

            # Header row preview
            if nr > 0:
                headers = [table.rows[0].cells[c].text[:20] for c in range(min(nc, 5))]
                hdr_str = " | ".join(headers)
                if nc > 5:
                    hdr_str += " | ..."
                lines.append(f"    Header: {hdr_str}")
                lines.append(f"    ({nr - 1} data rows)")

        elif child.tag == qn("w:sectPr"):
            pass  # section properties, already handled

    # Summary
    lines.append("")
    lines.append("--- Summary ---")
    h_str = ", ".join(f"{k}:{v}" for k, v in sorted(h_counts.items()))
    lines.append(
        f"paragraphs: {para_count} | tables: {table_count} | images: {image_count} | headings: {sum(h_counts.values())} ({h_str})"
    )
    lines.append(f"styles: {', '.join(sorted(styles_used))}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# XLSX inspection
# ---------------------------------------------------------------------------


def inspect_xlsx(path: Path) -> str:
    """Inspect an Excel workbook and return a structured text summary.

    Args:
        path: Path to the ``.xlsx`` file.

    Returns:
        Sheet-by-sheet overview with dimensions, data preview, charts,
        and formatting info.
    """
    try:
        import openpyxl
    except ImportError:
        raise ImportError("openpyxl is not installed; run: pip install scrinium[office]")

    wb = openpyxl.load_workbook(str(path), read_only=False, data_only=True)
    try:
        lines: list[str] = []
        lines.append(f"=== XLSX: {path.name} ===")
        lines.append(f"sheets: {len(wb.sheetnames)} ({', '.join(wb.sheetnames)})")
        lines.append("")

        total_rows = 0

        for ws_name in wb.sheetnames:
            ws = wb[ws_name]
            active_mark = " (active)" if ws == wb.active else ""
            lines.append(f'--- Sheet "{ws_name}"{active_mark} ---')

            dims = ws.dimensions or "?"
            mr = ws.max_row or 0
            mc = ws.max_column or 0
            total_rows += mr
            lines.append(f"  range: {dims} ({mr} rows x {mc} cols)")

            # Frozen panes
            if ws.freeze_panes:
                lines.append(f"  freeze panes: {ws.freeze_panes}")

            # Auto-filter
            if ws.auto_filter and ws.auto_filter.ref:
                lines.append(f"  auto filter: {ws.auto_filter.ref}")

            # Merged cells
            if ws.merged_cells.ranges:
                merges = [str(r) for r in list(ws.merged_cells.ranges)[:5]]
                merge_str = ", ".join(merges)
                if len(ws.merged_cells.ranges) > 5:
                    merge_str += f" ... (+{len(ws.merged_cells.ranges) - 5})"
                lines.append(f"  merged cells: {merge_str}")

            # Header row (row 1)
            if mr > 0 and mc > 0:
                headers = []
                for c in range(1, min(mc + 1, 8)):
                    val = ws.cell(row=1, column=c).value
                    headers.append(str(val)[:25] if val is not None else "")
                hdr_str = " | ".join(headers)
                if mc > 7:
                    hdr_str += " | ..."
                lines.append(f"  header (row 1): {hdr_str}")

            # Data preview (rows 2-4)
            preview_rows = min(mr, 4) - 1
            if preview_rows > 0:
                lines.append("  data preview:")
                for r in range(2, 2 + preview_rows):
                    vals = []
                    for c in range(1, min(mc + 1, 8)):
                        val = ws.cell(row=r, column=c).value
                        s = str(val)[:25] if val is not None else ""
                        vals.append(s)
                    lines.append(f"    Row {r}: {' | '.join(vals)}")

            # Charts
            if ws._charts:
                lines.append(f"  charts: {len(ws._charts)}")
                for ci, chart in enumerate(ws._charts, 1):
                    chart_type = type(chart).__name__
                    # Extract title string from openpyxl chart title object
                    title_str = "(untitled)"
                    if chart.title:
                        if isinstance(chart.title, str):
                            title_str = chart.title
                        else:
                            # openpyxl Title object — extract text from rich text runs
                            try:
                                for para in chart.title.tx.rich.paragraphs:
                                    for run in para.r:
                                        if run.t:
                                            title_str = run.t
                                            break
                                    if title_str != "(untitled)":
                                        break
                            except (AttributeError, TypeError):
                                title_str = str(chart.title)[:40]
                    lines.append(f'    [{ci}] {chart_type}: "{title_str}"')

            lines.append("")

        # Summary
        chart_total = sum(len(wb[s]._charts) for s in wb.sheetnames)
        lines.append("--- Summary ---")
        lines.append(f"sheets: {len(wb.sheetnames)} | total rows: ~{total_rows} | charts: {chart_total}")

        return "\n".join(lines)
    finally:
        wb.close()

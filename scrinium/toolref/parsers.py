from __future__ import annotations

import json
import re
import textwrap
from html import unescape
from pathlib import Path

from .manifest import _extract_html_anchor_fragment, _extract_html_main
from .search import _normalize_alias_phrase


def _parse_qe_def(filepath: Path) -> list[dict]:
    text = filepath.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"-program\s+(\S+)", text)
    program = m.group(1).strip("{}") if m else filepath.stem.replace("INPUT_", "").lower()
    records: list[dict] = []
    current_namelist = ""

    def _extract_braced(s: str, start: int) -> tuple[str, int]:
        if start >= len(s) or s[start] != "{":
            return "", start
        depth = 0
        i = start
        while i < len(s):
            if s[i] == "{":
                depth += 1
            elif s[i] == "}":
                depth -= 1
                if depth == 0:
                    return s[start + 1 : i], i + 1
            i += 1
        return s[start + 1 :], len(s)

    def _clean_text(t: str) -> str:
        t = re.sub(r"@b\s*\{([^}]*)\}", r"\1", t)
        t = re.sub(r"@i\s*\{([^}]*)\}", r"\1", t)
        t = re.sub(r"@ref\s+(\w+)", r"\1", t)
        t = re.sub(r"@tt\s*\{([^}]*)\}", r"\1", t)
        t = re.sub(r"@br\b", "\n", t)
        t = re.sub(r"@[a-z]+\s*", "", t)
        return textwrap.dedent(t).strip()

    def _parse_var_block(block: str, var_name: str) -> dict:
        def _match_braced(field: str) -> str:
            match = re.search(rf"{field}\s*\{{", block)
            if not match:
                return ""
            value, _ = _extract_braced(block, match.end() - 1)
            return _clean_text(value)

        vtype = ""
        tm = re.search(r"-type\s+(\S+)", block)
        if tm:
            vtype = tm.group(1)
        status = ""
        sm = re.search(r"status\s*\{([^}]*)\}", block)
        if sm:
            status = sm.group(1).strip()
        default_val = _match_braced("default")
        info_text = _match_braced("info")
        options_text = ""
        om = re.search(r"options\s*\{", block)
        if om:
            raw_options_text, _ = _extract_braced(block, om.end() - 1)
            opts = re.findall(r"opt\s+-val\s+'([^']+)'", raw_options_text)
            option_info = re.findall(r"info\s*\{([^}]*)\}", raw_options_text)
            if opts:
                options_text = "Options: " + ", ".join(opts)
                if option_info:
                    options_text += "\n" + _clean_text(" ".join(option_info))
        parts = []
        if vtype:
            parts.append(f"Type: {vtype}")
        if default_val:
            parts.append(f"Default: {default_val}")
        if status:
            parts.append(f"Status: {status}")
        synopsis = "; ".join(parts) if parts else ""
        content_parts = []
        if synopsis:
            content_parts.append(synopsis)
        if info_text:
            content_parts.append(info_text)
        if options_text:
            content_parts.append(options_text)
        content = "\n\n".join(content_parts)
        return {
            "var_type": vtype,
            "default_val": default_val,
            "synopsis": synopsis,
            "content": content if content else f"{var_name}: {vtype}",
        }

    pos = 0
    while pos < len(text):
        nm = re.match(r"\s*namelist\s+(\w+)\s*\{", text[pos:])
        if nm:
            current_namelist = nm.group(1)
            pos += nm.end()
            continue
        vm = re.match(r"\s*var\s+([\w()]+)\s*(?:-type\s+(\S+))?\s*\{", text[pos:])
        if vm:
            var_name = vm.group(1)
            brace_start = pos + vm.end() - 1
            block, end = _extract_braced(text, brace_start)
            parsed = _parse_var_block(f"-type {vm.group(2)} " + block if vm.group(2) else block, var_name)
            page_name = f"{program}/{current_namelist}/{var_name}".strip("/")
            records.append(
                {
                    "program": program,
                    "section": current_namelist,
                    "page_name": page_name,
                    "title": var_name,
                    "category": "variable",
                    **parsed,
                }
            )
            pos = end
            continue
        dm = re.match(r"\s*dimension\s+([\w()]+)\s+.*?-type\s+(\S+)\s*\{", text[pos:])
        if dm:
            var_name = dm.group(1)
            brace_start = pos + dm.end() - 1
            block, end = _extract_braced(text, brace_start)
            parsed = _parse_var_block(f"-type {dm.group(2)} " + block, var_name)
            page_name = f"{program}/{current_namelist}/{var_name}".strip("/")
            records.append(
                {
                    "program": program,
                    "section": current_namelist,
                    "page_name": page_name,
                    "title": var_name,
                    "category": "dimension",
                    **parsed,
                }
            )
            pos = end
            continue
        vgm = re.match(r"\s*vargroup\s+.*?-type\s+(\S+)\s*\{", text[pos:])
        if vgm:
            brace_start = pos + vgm.end() - 1
            block, end = _extract_braced(text, brace_start)
            vg_vars = re.findall(r"var\s+(\w+)", block)
            if vg_vars:
                parsed = _parse_var_block(f"-type {vgm.group(1)} " + block, ", ".join(vg_vars))
                for vn in vg_vars:
                    page_name = f"{program}/{current_namelist}/{vn}".strip("/")
                    records.append(
                        {
                            "program": program,
                            "section": current_namelist,
                            "page_name": page_name,
                            "title": vn,
                            "category": "vargroup",
                            **parsed,
                        }
                    )
            pos = end
            continue
        cm = re.match(r"\s*card\s+([\w_]+)\s*\{", text[pos:])
        if cm:
            card_name = cm.group(1)
            brace_start = pos + cm.end() - 1
            block, end = _extract_braced(text, brace_start)
            page_name = f"{program}/card/{card_name}"
            records.append(
                {
                    "program": program,
                    "section": "card",
                    "page_name": page_name,
                    "title": card_name,
                    "category": "card",
                    "var_type": "",
                    "default_val": "",
                    "synopsis": f"Input card: {card_name}",
                    "content": _clean_text(block)[:4000],
                }
            )
            pos = end
            continue
        pos += 1
    return records


def _parse_lammps_rst(filepath: Path) -> list[dict]:
    text = filepath.read_text(encoding="utf-8", errors="replace")
    stem = filepath.stem
    commands = [
        c.strip()
        for c in re.findall(r"\.\.\s+index::\s+(.+)", text)
        if all(x not in c for x in ("/gpu", "/intel", "/kk", "/omp", "/opt"))
    ]
    alias_commands: list[str] = []
    for command in commands:
        normalized_command = _normalize_alias_phrase(command)
        if normalized_command and normalized_command not in alias_commands:
            alias_commands.append(normalized_command)
    title_match = re.search(r"^(.+?)\n={3,}", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else stem
    category = "other"
    for prefix in (
        "fix_",
        "compute_",
        "pair_",
        "bond_",
        "angle_",
        "dihedral_",
        "improper_",
        "dump_",
        "region_",
        "group_",
    ):
        if stem.startswith(prefix):
            category = prefix.rstrip("_")
            break
    sections: dict[str, str] = {}
    section_pattern = re.compile(r'^(.+)\n"{3,}', re.MULTILINE)
    matches = list(section_pattern.finditer(text))
    for i, m in enumerate(matches):
        sec_name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[sec_name.lower()] = text[start:end].strip()
    synopsis = ""
    if "syntax" in sections:
        cb = re.search(r"\.\.\s+code-block::\s+LAMMPS\s*\n\n((?:\s+.+\n?)+)", sections["syntax"])
        if cb:
            synopsis = cb.group(1).strip().split("\n")[0].strip()
    if alias_commands:
        alias_text = ", ".join(alias_commands[:12])
        synopsis = f"{synopsis} | Aliases: {alias_text}" if synopsis else f"Aliases: {alias_text}"
    content_parts = []
    if alias_commands:
        content_parts.append("Alias keys: " + " ".join(f"|{alias}|" for alias in alias_commands[:20]))
        content_parts.append("Aliases:\n" + "\n".join(f"- {alias}" for alias in alias_commands[:20]))
    if "syntax" in sections:
        content_parts.append("Syntax:\n" + sections["syntax"][:1000])
    if "description" in sections:
        content_parts.append("Description:\n" + sections["description"][:3000])
    if "restrictions" in sections:
        content_parts.append("Restrictions:\n" + sections["restrictions"][:500])
    if "default" in sections:
        content_parts.append("Default:\n" + sections["default"][:300])
    content = "\n\n".join(content_parts) if content_parts else text[:2000]
    return [
        {
            "program": "lammps",
            "section": category,
            "page_name": f"lammps/{stem}",
            "title": title,
            "category": category,
            "var_type": "",
            "default_val": sections.get("default", "")[:200].strip(),
            "synopsis": synopsis,
            "content": content,
        }
    ]


def _parse_gromacs_rst(filepath: Path) -> list[dict]:
    text = filepath.read_text(encoding="utf-8", errors="replace")
    stem = filepath.stem
    records: list[dict] = []
    if stem == "mdp-options":
        starts = list(re.finditer(r"(?m)^\.\.\s+mdp::\s+(\S+)\s*$", text))
        for idx, match in enumerate(starts):
            param_name = match.group(1).strip()
            start = match.end()
            end = starts[idx + 1].start() if idx + 1 < len(starts) else len(text)
            block = text[start:end].strip()
            values = [v.strip() for v in re.findall(r"(?m)^\s*\.\.\s+mdp-value::\s+(.+?)\s*$", block)]
            cleaned_lines: list[str] = []
            for line in block.splitlines():
                stripped = line.strip()
                if stripped.startswith(".. mdp-value::"):
                    cleaned_lines.append(f"Option: {stripped.split('::', 1)[1].strip()}")
                    continue
                cleaned_lines.append(line.rstrip())
            cleaned = "\n".join(cleaned_lines)
            cleaned = re.sub(r":mdp:`([^`]+)`", r"\1", cleaned)
            cleaned = re.sub(r":mdp-value:`([^`]+)`", r"\1", cleaned)
            cleaned = re.sub(r"\s+\n", "\n", cleaned)
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
            synopsis = "MDP parameter"
            if values:
                synopsis += f" | Options: {', '.join(values[:8])}"
            records.append(
                {
                    "program": "gromacs",
                    "section": "mdp",
                    "page_name": f"gromacs/mdp/{param_name}",
                    "title": param_name,
                    "category": "mdp",
                    "var_type": "",
                    "default_val": "",
                    "synopsis": synopsis,
                    "content": f"{param_name}\n\n{cleaned[:3000]}",
                }
            )
        return records
    title_match = re.search(r"^(.+?)\n={3,}", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else stem
    section = "general"
    if "user-guide" in str(filepath):
        section = "user-guide"
    elif "reference-manual" in str(filepath):
        section = "reference-manual"
    elif "how-to" in str(filepath):
        section = "how-to"
    records.append(
        {
            "program": "gromacs",
            "section": section,
            "page_name": f"gromacs/{section}/{stem}",
            "title": title,
            "category": section,
            "var_type": "",
            "default_val": "",
            "synopsis": title,
            "content": text[:5000],
        }
    )
    return records


def _html_to_text(text: str) -> str:
    body = _extract_html_main(text)
    body = re.sub(r"<(script|style|noscript|svg)\b.*?</\1>", "", body, flags=re.IGNORECASE | re.DOTALL)
    code_blocks: list[str] = []

    def _stash_code(m: re.Match[str]) -> str:
        block = unescape(m.group(1))
        block = re.sub(r"<[^>]+>", "", block)
        token = f"__CODE_BLOCK_{len(code_blocks)}__"
        code_blocks.append(block.strip())
        return f"\n{token}\n"

    body = re.sub(r"<pre\b[^>]*>(.*?)</pre>", _stash_code, body, flags=re.IGNORECASE | re.DOTALL)
    body = re.sub(r"<code\b[^>]*>(.*?)</code>", _stash_code, body, flags=re.IGNORECASE | re.DOTALL)
    body = re.sub(r"</(h\d|p|div|section|article|li|tr|table|ul|ol)>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"<li\b[^>]*>", "- ", body, flags=re.IGNORECASE)
    body = re.sub(r"<[^>]+>", "", body)
    body = unescape(body)
    for idx, block in enumerate(code_blocks):
        body = body.replace(f"__CODE_BLOCK_{idx}__", f"\n{block}\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in body.splitlines()]
    compact = []
    blank = False
    for line in lines:
        if not line:
            if not blank:
                compact.append("")
            blank = True
            continue
        compact.append(line)
        blank = False
    return "\n".join(compact).strip()


def _clean_manifest_text(text: str, title: str, program: str) -> str:
    anchor_patterns: list[tuple[str, bool]] = []
    if "BLAST" in title.upper():
        anchor_patterns.append((r"BLAST[^\n]*User Manual", True))
    anchor_patterns.extend([(title, False), (program, False), (program.replace(".x", ""), False)])
    for anchor, is_regex in anchor_patterns:
        if not anchor:
            continue
        if is_regex:
            m = re.search(anchor, text)
            if m and m.start() > 0:
                text = text[m.start() :]
                break
        elif anchor in text:
            pos = text.find(anchor)
            if pos > 0:
                text = text[pos:]
                break
    for marker in ("Search results", "Found a content problem with this page?", "Want to get more involved?"):
        pos = text.find(marker)
        if pos > 0:
            text = text[:pos]
    cleaned_lines: list[str] = []
    skip_exact = {"Top", "Bookshelf", "Toggle navigation", "Doc", "Src", "Search", "< PrevNext >"}
    skip_prefixes = ("Copyright", "Last updated:", "Author(s):", "This work is licensed under")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            cleaned_lines.append("")
            continue
        if line in skip_exact or any(line.startswith(prefix) for prefix in skip_prefixes):
            continue
        if line in {"- navigation", "- solvers", "- system", "- incompressible", "- compressible"}:
            continue
        line = line.replace("ð", "").replace("Â©", "©").replace("â", "").strip()
        cleaned_lines.append(line)
    compact: list[str] = []
    blank = False
    for line in cleaned_lines:
        if not line:
            if not blank:
                compact.append("")
            blank = True
            continue
        compact.append(line)
        blank = False
    return "\n".join(compact).strip()


def _pick_manifest_synopsis(lines: list[str], title: str) -> str:
    for line in lines:
        if (
            not line
            or line == title
            or line.startswith("-")
            or line.startswith("/*")
            or line.startswith("|")
            or line.startswith("\\")
        ):
            continue
        if line in {"Overview", "Usage", "Further information", "Input requirements", "Boundary conditions"}:
            continue
        return line[:200]
    return ""


def _parse_manifest_html(filepath: Path) -> list[dict]:
    meta = json.loads(filepath.with_suffix(".json").read_text(encoding="utf-8"))
    raw_html = filepath.read_text(encoding="utf-8", errors="replace")
    if meta.get("anchor"):
        raw_html = _extract_html_anchor_fragment(raw_html, meta["anchor"])
    text = _html_to_text(raw_html)
    title = meta.get("title", "")
    if not title:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
        title = unescape(title_match.group(1)).strip() if title_match else meta["page_name"]
    text = _clean_manifest_text(text, title, meta.get("program", ""))
    lines = [line for line in text.splitlines() if line.strip()]
    synopsis = _pick_manifest_synopsis(lines, title)
    if meta.get("section") == "dictionary" and (
        not synopsis or synopsis in {"FoamFile"} or synopsis.startswith("/*") or synopsis.startswith("FoamFile")
    ):
        synopsis = f"{title} dictionary"
    return [
        {
            "program": meta.get("program", ""),
            "section": meta.get("section", ""),
            "page_name": meta["page_name"],
            "title": title,
            "category": meta.get("section", ""),
            "var_type": "",
            "default_val": "",
            "synopsis": synopsis,
            "content": text[:5000],
        }
    ]

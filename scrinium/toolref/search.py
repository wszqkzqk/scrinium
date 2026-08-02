from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING

from .paths import _db_path, validate_tool_name
from .storage import _get_current

if TYPE_CHECKING:
    from scrinium.config import Config


def _normalize_program_filter(tool: str, program: str) -> str:
    prog = program.lower().strip()
    if tool == "qe" and prog and not prog.endswith(".x"):
        prog += ".x"
    return prog


def _normalize_alias_phrase(*parts: str) -> str:
    phrase = " ".join((p or "").strip().lower() for p in parts if p and p.strip())
    phrase = phrase.replace("_", " ")
    phrase = re.sub(r"\s+", " ", phrase)
    return phrase.strip()


def _tokenize_rank_text(text: str) -> list[str]:
    normalized = _normalize_alias_phrase(text)
    return [token for token in normalized.split() if token]


def _expanded_terms(query: str) -> list[str]:
    return [part.strip().lower() for part in re.split(r"\s+or\s+", query, flags=re.IGNORECASE) if part.strip()]


def _normalize_search_query(query: str) -> str:
    normalized = re.sub(r"[-_/]+", " ", query).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized or query.strip()


def _expand_search_query(tool: str, query: str) -> str:
    normalized = _normalize_search_query(query).lower()
    expansions: list[str] = [normalized]

    if tool == "openfoam":
        if "drag coefficient" in normalized or "drag coefficients" in normalized:
            expansions.extend(["forces", "force coeffs", "forcecoeffs"])
        if "force coefficients" in normalized:
            expansions.extend(["forces", "force coeffs", "forcecoeffs"])
        if "q criterion" in normalized:
            expansions.extend(["function objects", "post processing", "qcriterion", "q"])
        if "y plus" in normalized:
            expansions.extend(["yplus", "wall function", "boundary layer"])
        if "wall shear stress" in normalized:
            expansions.extend(["wallshearstress", "wall shear", "shear stress"])
        if "solver residuals" in normalized or normalized == "residuals":
            expansions.extend(["residuals", "linear solver", "convergence"])
        if "k omega sst" in normalized or "k-omega sst" in normalized or "sst turbulence" in normalized:
            expansions.extend(["komegasst", "turbulence model", "ras model", "sst"])
        if "numerical schemes" in normalized:
            expansions.extend(["fvschemes", "discretisation schemes", "fv schemes"])
        if "linear solver settings" in normalized or "solver settings" in normalized:
            expansions.extend(["fvsolution", "linear solver", "solver controls"])
    elif tool == "lammps":
        if "phase transition pressure" in normalized or "shock pressure" in normalized:
            expansions.extend(["fix_nphug", "fix_msst", "fix_qbmsst", "shock"])
    elif tool == "qe":
        if "ecut rho" in normalized:
            expansions.append("ecutrho")
        if "ecut wfc" in normalized:
            expansions.append("ecutwfc")
    elif tool == "gromacs":
        if "parrinello rahman" in normalized or "parrinello-rahman" in normalized:
            expansions.extend(["pcoupl", "barostat", "pressure coupling"])
        if "v rescale thermostat" in normalized or "v-rescale thermostat" in normalized:
            expansions.extend(["tcoupl", "v rescale", "temperature coupling", "tau t", "ref t"])
        if "nose hoover thermostat" in normalized or "nose-hoover thermostat" in normalized:
            expansions.extend(["tcoupl", "nose hoover", "temperature coupling", "tau t"])
        if "constraints h bonds" in normalized or "constraints h-bonds" in normalized:
            expansions.extend(["constraints", "h bonds", "constraint algorithm"])
        if normalized == "temperature coupling" or "temperature coupling" in normalized:
            expansions.extend(["tcoupl", "tau t", "ref t"])
        if normalized == "pressure coupling" or "pressure coupling" in normalized:
            expansions.extend(["pcoupl", "pcoupltype", "tau p", "ref p"])
    elif tool == "bioinformatics":
        if "phylogenetic tree" in normalized:
            expansions.extend(["iqtree", "mafft", "phylogenetics"])
        if "bootstrap tree" in normalized or "bootstrap support" in normalized or "ultrafast bootstrap" in normalized:
            expansions.extend(["iqtree", "ultrafast bootstrap", "ufboot", "phylogenetics"])
        if "read mapping" in normalized or "long read" in normalized or "nanopore" in normalized:
            expansions.extend(["minimap2", "alignment", "long reads", "ont"])
        if "multiple sequence alignment" in normalized or "msa" in normalized:
            expansions.extend(["mafft", "alignment", "fasta"])
        if "bam indexing" in normalized or "index bam" in normalized:
            expansions.extend(["samtools index", "samtools", "bam index"])
        if "mutation" in normalized:
            expansions.extend(["bcftools", "samtools", "variant calling"])
        if "variant calling" in normalized or "vcf" in normalized:
            expansions.extend(["bcftools", "bcftools call", "bcftools mpileup"])
        if "protein structure" in normalized or "folding" in normalized:
            expansions.extend(["esmfold", "protein structure prediction", "transformers"])

    deduped: list[str] = []
    for item in expansions:
        if item and item not in deduped:
            deduped.append(item)
    return " OR ".join(deduped) if len(deduped) > 1 else deduped[0]


def _score_search_result(tool: str, normalized_query: str, expanded_query: str, row: sqlite3.Row) -> tuple[int, float]:
    title = (row["title"] or "").lower()
    page_name = (row["page_name"] or "").lower()
    synopsis = (row["synopsis"] or "").lower()
    content = (row["content"] or "").lower()
    section = (row["section"] or "").lower()
    program = (row["program"] or "").lower()
    rank = float(row["rank"]) if row["rank"] is not None else 0.0

    score = 0
    normalized_slug = normalized_query.replace(" ", "-")
    normalized_snake = normalized_query.replace(" ", "_")
    query_tokens = _tokenize_rank_text(normalized_query)
    expanded_terms = _expanded_terms(expanded_query)

    if normalized_query and title == normalized_query:
        score += 120
    if normalized_query and (
        page_name.endswith(f"/{normalized_query}")
        or page_name.endswith(f"/{normalized_slug}")
        or page_name.endswith(f"/{normalized_snake}")
    ):
        score += 110
    if normalized_query and normalized_query in synopsis:
        score += 90
    if normalized_query and normalized_query in content:
        score += 70

    for term in expanded_terms:
        if not term or term == normalized_query:
            continue
        if title == term:
            score += 80
        if page_name.endswith(f"/{term}") or page_name.endswith(f"/{term.replace(' ', '-')}"):
            score += 75
        if term in synopsis:
            score += 55
        if term in content:
            score += 35

    if query_tokens:
        synopsis_hits = sum(1 for token in query_tokens if token in synopsis)
        content_hits = sum(1 for token in query_tokens if token in content)
        title_hits = sum(1 for token in query_tokens if token in title)
        score += title_hits * 18 + synopsis_hits * 12 + content_hits * 6

    if tool == "gromacs" and section == "mdp":
        score += 20
        if normalized_query == "pressure coupling":
            if page_name.endswith("/pcoupl"):
                score += 90
            if page_name.endswith("/pcoupltype"):
                score += 40
        if normalized_query == "temperature coupling" and page_name.endswith("/tcoupl"):
            score += 90
    if tool == "bioinformatics":
        if (
            "multiple sequence alignment" in normalized_query or normalized_query.startswith("msa")
        ) and program == "mafft":
            score += 140
        if (
            "bam indexing" in normalized_query
            or "samtools index" in normalized_query
            or "index bam" in normalized_query
        ) and page_name.endswith("/index"):
            score += 140
        if (
            "read mapping" in normalized_query or "nanopore" in normalized_query or "long read" in normalized_query
        ) and program == "minimap2":
            score += 120
        if ("variant calling" in normalized_query or "vcf" in normalized_query) and program == "bcftools":
            score += 110
        if (
            "phylogenetic tree" in normalized_query or "ultrafast bootstrap" in normalized_query
        ) and program == "iqtree":
            score += 120

    return score, rank


def _build_toolref_search_sql(
    match_query: str,
    tool: str,
    version: str | None,
    program: str | None,
    section: str | None,
    normalized_query: str,
    alias_phrase: str,
    top_k: int,
) -> tuple[str, list]:
    sql = """
        SELECT p.*, rank
        FROM toolref_fts f
        JOIN toolref_pages p ON f.rowid = p.id
        WHERE toolref_fts MATCH ?
          AND p.tool = ?
    """
    params: list = [match_query, tool]

    if version:
        sql += " AND p.version = ?"
        params.append(version)
    if program:
        prog = _normalize_program_filter(tool, program)
        sql += " AND LOWER(p.program) = ?"
        params.append(prog)
    if section:
        sql += " AND LOWER(p.section) = ?"
        params.append(section.lower())

    sql += """
        ORDER BY
          CASE
            WHEN LOWER(p.title) = ? THEN 0
            WHEN LOWER(p.content) LIKE ? THEN 1
            WHEN LOWER(p.page_name) = ? OR LOWER(p.page_name) LIKE ? THEN 2
            WHEN LOWER(p.synopsis) LIKE ? THEN 3
            ELSE 4
          END,
          rank
        LIMIT ?
    """
    params.extend(
        [
            normalized_query.lower(),
            f"%|{alias_phrase}|%",
            normalized_query.lower(),
            f"%/{normalized_query.lower().replace(' ', '_')}",
            f"%{alias_phrase}%",
            top_k,
        ]
    )
    return sql, params


def toolref_show(tool: str, *args: str, cfg: Config | None = None) -> list[dict]:
    if not validate_tool_name(tool):
        raise ValueError(f"未知工具：{tool}")

    db = _db_path(tool, cfg)
    if not db.exists():
        raise FileNotFoundError(f"{tool} 文档未索引。请先运行 `scrinium toolref fetch {tool}`")

    version = _get_current(tool, cfg)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    query_parts = [a.lower() for a in args]
    query_str = "/".join(query_parts)
    alias_phrase = _normalize_alias_phrase(*query_parts)

    rows = conn.execute(
        """SELECT * FROM toolref_pages
           WHERE tool = ? AND (version = ? OR ? IS NULL)
           AND (LOWER(page_name) = ? OR LOWER(page_name) = ?)""",
        (tool, version, version, query_str, f"{tool}/{query_str}"),
    ).fetchall()

    if not rows and tool == "qe" and len(query_parts) >= 2:
        program = _normalize_program_filter(tool, query_parts[0])
        title_query = query_parts[-1]
        rows = conn.execute(
            """SELECT * FROM toolref_pages
               WHERE tool = ? AND (version = ? OR ? IS NULL)
               AND LOWER(program) = ? AND LOWER(title) = ?
               ORDER BY LENGTH(page_name)
               LIMIT 20""",
            (tool, version, version, program, title_query),
        ).fetchall()

    if not rows and alias_phrase:
        exact_alias_key = f"%|{alias_phrase}|%"
        rows = conn.execute(
            """SELECT * FROM toolref_pages
               WHERE tool = ? AND (version = ? OR ? IS NULL)
               AND LOWER(content) LIKE ?
               ORDER BY LENGTH(page_name)
               LIMIT 20""",
            (tool, version, version, exact_alias_key),
        ).fetchall()

    if not rows:
        suffix_pattern = f"%/{query_str}"
        rows = conn.execute(
            """SELECT * FROM toolref_pages
               WHERE tool = ? AND (version = ? OR ? IS NULL)
               AND LOWER(page_name) LIKE ?
               LIMIT 20""",
            (tool, version, version, suffix_pattern),
        ).fetchall()

    if not rows:
        like_pattern = f"%{'%'.join(query_parts)}%"
        rows = conn.execute(
            """SELECT * FROM toolref_pages
               WHERE tool = ? AND (version = ? OR ? IS NULL)
               AND LOWER(page_name) LIKE ?
               LIMIT 20""",
            (tool, version, version, like_pattern),
        ).fetchall()

    if not rows:
        title_query = query_parts[-1] if query_parts else ""
        rows = conn.execute(
            """SELECT * FROM toolref_pages
               WHERE tool = ? AND (version = ? OR ? IS NULL)
               AND LOWER(title) = ?
               LIMIT 20""",
            (tool, version, version, title_query),
        ).fetchall()

    if not rows and len(query_parts) == 1:
        rows = conn.execute(
            """SELECT * FROM toolref_pages
               WHERE tool = ? AND (version = ? OR ? IS NULL)
               AND LOWER(program) = ?
               ORDER BY
                 CASE
                   WHEN LOWER(page_name) LIKE '%/manual' THEN 0
                   WHEN LOWER(page_name) LIKE '%/command-reference' THEN 1
                   ELSE 2
                 END,
                 LENGTH(page_name)
               LIMIT 20""",
            (tool, version, version, query_parts[0]),
        ).fetchall()

    if not rows and alias_phrase:
        like_alias = f"%{alias_phrase}%"
        exact_alias_key = f"%|{alias_phrase}|%"
        rows = conn.execute(
            """SELECT * FROM toolref_pages
               WHERE tool = ? AND (version = ? OR ? IS NULL)
               AND (LOWER(synopsis) LIKE ? OR LOWER(content) LIKE ?)
               ORDER BY
                 CASE
                   WHEN LOWER(content) LIKE ? THEN 0
                   WHEN LOWER(synopsis) LIKE ? THEN 1
                   ELSE 2
                 END,
                 LENGTH(page_name)
               LIMIT 20""",
            (tool, version, version, like_alias, like_alias, exact_alias_key, like_alias),
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def toolref_search(
    tool: str,
    query: str,
    *,
    top_k: int = 20,
    program: str | None = None,
    section: str | None = None,
    cfg: Config | None = None,
) -> list[dict]:
    """Full-text search over tool documentation."""
    if not validate_tool_name(tool):
        raise ValueError(f"未知工具：{tool}")

    db = _db_path(tool, cfg)
    if not db.exists():
        raise FileNotFoundError(f"{tool} 文档未索引。请先运行 `scrinium toolref fetch {tool}`")

    version = _get_current(tool, cfg)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    normalized_query = _normalize_search_query(query)
    expanded_query = _expand_search_query(tool, query)
    alias_phrase = _normalize_alias_phrase(normalized_query)

    # build FTS5 query — auto-convert spaces to OR for better recall
    fts_query = expanded_query
    if " " in expanded_query and not any(kw in expanded_query.upper() for kw in ("OR", "AND", "NOT", '"')):
        words = expanded_query.split()
        fts_query = " OR ".join(words)

    try:
        sql, params = _build_toolref_search_sql(
            fts_query,
            tool,
            version,
            program,
            section,
            normalized_query,
            alias_phrase,
            top_k,
        )
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        # FTS query syntax error — try quoting
        safe_query = '"' + normalized_query.replace('"', "") + '"'
        try:
            sql, params = _build_toolref_search_sql(
                safe_query,
                tool,
                version,
                program,
                section,
                normalized_query,
                alias_phrase,
                top_k,
            )
            rows = conn.execute(sql, params).fetchall()
        except Exception:
            rows = []

    conn.close()
    scored_rows = [
        (_score_search_result(tool, normalized_query.lower(), expanded_query.lower(), row), row) for row in rows
    ]
    scored_rows.sort(key=lambda item: (-item[0][0], item[0][1]))
    return [dict(row) for _, row in scored_rows[:top_k]]

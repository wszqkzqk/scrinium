"""
metadata — Paper metadata extraction, API lookup, JSON output, and file renaming
================================================================================

Extracts metadata (title, authors, year, DOI, journal) from academic paper
markdown converted by MinerU; queries citation counts, abstracts, and paper types
via the Crossref, Semantic Scholar, and OpenAlex APIs; writes a sibling JSON
metadata file; and renames the md + json files to {first-author}-{year}-{full-title}.

Submodules:
    _models   — PaperMetadata dataclass + constants + HTTP session
    _extract  — Markdown regex parsing (title/authors/doi/year/journal)
    _api      — API queries (Crossref/S2/OA) + enrich_metadata
    _abstract — Abstract extraction (regex/DOI fetch/backfill)
    _writer   — JSON serialization + file renaming
    _cli      — Standalone CLI commands
"""

# Re-export all public names so existing imports remain unchanged:
#   from scrinium.ingest.metadata import PaperMetadata, enrich_metadata, ...

from ._abstract import (  # noqa: F401
    _clean_abstract,
    _regex_extract_abstract,
    backfill_abstracts,
    extract_abstract_from_md,
    fetch_abstract_by_doi,
)
from ._api import (  # noqa: F401
    _fuzzy_title_match,
    _title_keywords,
    enrich_metadata,
    query_crossref,
    query_openalex,
    query_semantic_scholar,
)
from ._cli import main  # noqa: F401
from ._extract import (  # noqa: F401
    _clean_author_name,
    _clean_author_text,
    _extract_authors,
    _extract_authors_from_h1_before_title,
    _extract_doi,
    _extract_from_filename,
    _extract_journal,
    _extract_lastname,
    _extract_text_from_latex,
    _extract_title,
    _extract_year_from_text,
    _split_authors,
    extract_metadata_from_markdown,
)
from ._models import PaperMetadata, configure_s2_session  # noqa: F401
from ._writer import (  # noqa: F401
    _clean_title_for_filename,
    _sanitize_for_filename,
    _strip_diacritics,
    generate_new_stem,
    metadata_to_dict,
    refetch_metadata,
    rename_files,
    rename_paper,
    write_metadata_json,
)

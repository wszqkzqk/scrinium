"""
metadata — 论文元数据提取、API 查询、JSON 输出与文件重命名
==========================================================

从 MinerU 转换的学术论文 markdown 文件中提取元数据（标题、作者、年份、DOI、期刊），
通过 Crossref / Semantic Scholar / OpenAlex 三个 API 查询引用量、摘要、论文类型，
输出同名 JSON 元数据文件，并将 md + json 重命名为 {一作}-{年份}-{完整标题} 格式。

子模块:
    _models   — PaperMetadata dataclass + 常量 + HTTP session
    _extract  — markdown 正则解析（title/authors/doi/year/journal）
    _api      — API 查询（Crossref/S2/OA）+ enrich_metadata
    _abstract — abstract 提取（regex/LLM/DOI fetch/backfill）
    _writer   — JSON 序列化 + 文件重命名
    _cli      — 独立 CLI 命令
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

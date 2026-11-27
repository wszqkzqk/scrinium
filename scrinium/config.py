"""
config.py -- Scrinium configuration loading.

Precedence (highest to lowest):
  1. config.local.yaml (git-ignored; API keys and sensitive values)
  2. config.yaml (primary configuration)
  3. Built-in defaults

Search order for config.yaml:
  1. Explicit ``config_path`` argument
  2. SCRINIUM_CONFIG environment variable (legacy SCHOLARAIO_CONFIG warns on use)
  3. Upward directory walk from the current working directory
  4. ~/.scrinium/config.yaml (global config for plugin mode; falls back to
     legacy ~/.scholaraio/config.yaml with a migration notice)

Removed sections (llm/translate/embed/topics) emit a one-time deprecation
warning on load and are ignored; the framework never calls LLMs/embeddings.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_log = logging.getLogger(__name__)

# Deprecated pre-fork (ScholarAIO) environment variable names. The new
# SCRINIUM_* name always wins; the legacy name is honored with a
# deprecation warning when the new one is unset or empty.
_DEPRECATED_ENV_NAMES = {
    "SCRINIUM_CONFIG": "SCHOLARAIO_CONFIG",
}


def _env_with_fallback(new_name: str) -> str:
    """Read env var ``new_name``, falling back to its deprecated pre-fork name.

    Returns an empty string when neither name is set. A hit on the legacy
    ``SCHOLARAIO_*`` name logs a deprecation warning.
    """
    val = os.environ.get(new_name, "")
    if val:
        return val
    old_name = _DEPRECATED_ENV_NAMES.get(new_name)
    if old_name:
        old_val = os.environ.get(old_name, "")
        if old_val:
            _log.warning("environment variable %s is deprecated, use %s instead", old_name, new_name)
            return old_val
    return ""


VALID_LOCAL_MINERU_BACKENDS = {
    "pipeline",
    "vlm-auto-engine",
    "vlm-http-client",
    "hybrid-auto-engine",
    "hybrid-http-client",
}
VALID_PDF_CLOUD_MODEL_VERSIONS = {"pipeline", "vlm"}
VALID_MINERU_PARSE_METHODS = {"auto", "txt", "ocr"}
VALID_PDF_PREFERRED_PARSERS = {"mineru", "docling", "pymupdf"}

# ============================================================================
#  Config dataclasses
# ============================================================================


@dataclass
class PathsConfig:
    """File path configuration.

    Attributes:
        papers_dir: Ingested papers directory (relative to project root).
        index_db: SQLite index database path (relative to project root).
    """

    papers_dir: str = "data/papers"
    index_db: str = "data/index.db"


@dataclass
class SearchConfig:
    """FTS5 full-text search configuration.

    Attributes:
        top_k: Default result count for ``scrinium search``.
    """

    top_k: int = 20


@dataclass
class LogConfig:
    """Logging and metrics configuration.

    Attributes:
        level: Root console log level (``"DEBUG"`` | ``"INFO"`` | ``"WARNING"``).
        file: Log file path (relative to project root).
        max_bytes: Maximum bytes per log file before rotation.
        backup_count: Number of rotated log files to keep.
        metrics_db: Metrics database path (relative to project root).
    """

    level: str = "INFO"
    file: str = "data/scrinium.log"
    max_bytes: int = 10_000_000  # 10 MB
    backup_count: int = 3
    metrics_db: str = "data/metrics.db"


@dataclass
class IngestConfig:
    """Ingestion pipeline configuration.

    Attributes:
        mineru_endpoint: Local MinerU API endpoint.
        mineru_cloud_url: ``--base-url`` override for `mineru-open-api`
            (defaults to the official public endpoint; override for private deployments).
        mineru_api_key: MinerU token (prefer config.local.yaml or environment variable;
            mapped to ``MINERU_TOKEN`` for `mineru-open-api`).
        mineru_backend_local: Local MinerU backend (``pipeline`` | ``vlm-auto-engine`` |
            ``vlm-http-client`` | ``hybrid-auto-engine`` | ``hybrid-http-client``).
        mineru_model_version_cloud: Cloud PDF model version (``pipeline`` | ``vlm``).
        mineru_lang: MinerU OCR language (``ch`` | ``en`` | ``latin``, etc.).
        mineru_parse_method: Parse method (``auto`` | ``txt`` | ``ocr``); `mineru-open-api`
            only maps ``ocr`` to ``--ocr`` (``txt`` falls back to default with a warning).
        mineru_enable_formula: Enable formula parsing (cloud ``pipeline``/``vlm`` only).
        mineru_enable_table: Enable table parsing (cloud ``pipeline``/``vlm`` only).
        contact_email: Crossref polite pool contact email (prefer config.local.yaml).
        s2_api_key: Semantic Scholar API key for higher rate limits
            (1 req/s vs 100 req/5min; prefer config.local.yaml or ``S2_API_KEY``).
        openalex_api_key: OpenAlex API key for higher daily quota
            (prefer config.local.yaml or ``OPENALEX_API_KEY``).
        chunk_page_limit: Page threshold above which local MinerU splits large PDFs
            before conversion and merges the resulting Markdown. Cloud MinerU also
            enforces its official 600-page / 200MB per-file limit.
        mineru_batch_size: Batch size for the `mineru-open-api` compat layer (default 20).
        mineru_upload_workers: Concurrency limit for cloud CLI / compat-layer uploads.
        mineru_upload_retries: Retries per file for `mineru-open-api` uploads
            (including the first attempt, default 3; exponential backoff).
        mineru_download_retries: Legacy cloud download retry setting (kept for compatibility).
        mineru_poll_timeout: Timeout in seconds for one `mineru-open-api` conversion (default 900).
        enrich_timeout: Hard timeout in seconds per paper for metadata API enrichment
            (default 180; on timeout keeps local metadata with ``local_timeout``).
        pdf_preferred_parser: Preferred PDF parser (``mineru`` default; ``docling`` or
            ``pymupdf`` skips MinerU).
        pdf_fallback_order: Fallback parser order when MinerU is unavailable or fails
            (``docling`` / ``pymupdf`` / ``auto``).
        pdf_fallback_auto_detect: Auto-detect locally installed fallback parsers.
        si_fetch_on_ingest: Automatically fetch SI after ingesting new papers
            (rule chain -> download -> verify -> attach; failures never block ingest
            and record ``fetch_status`` for agent takeover).
    """

    mineru_endpoint: str = "http://localhost:8000"
    mineru_cloud_url: str = "https://mineru.net/api/v4"
    mineru_api_key: str = ""
    mineru_backend_local: str = "pipeline"
    mineru_model_version_cloud: str = "pipeline"
    mineru_lang: str = "ch"
    mineru_parse_method: str = "auto"
    mineru_enable_formula: bool = True
    mineru_enable_table: bool = True
    contact_email: str = ""
    s2_api_key: str = ""  # Semantic Scholar API key for higher rate limits
    openalex_api_key: str = ""  # OpenAlex API key for a higher daily budget
    chunk_page_limit: int = 100  # local MinerU auto-split threshold in pages
    mineru_batch_size: int = 20  # cloud batch size per request
    mineru_upload_workers: int = 4
    mineru_upload_retries: int = 3
    mineru_download_retries: int = 3
    mineru_poll_timeout: int = 900
    enrich_timeout: int = 180
    pdf_preferred_parser: str = "mineru"
    pdf_fallback_order: list[str] = field(default_factory=lambda: ["auto"])
    pdf_fallback_auto_detect: bool = True
    si_fetch_on_ingest: bool = True


@dataclass
class ZoteroConfig:
    """Zotero integration configuration.

    Attributes:
        api_key: Zotero Web API key.
        library_id: Zotero user or group library ID.
        library_type: Library type (``"user"`` or ``"group"``).
    """

    api_key: str = ""
    library_id: str = ""
    library_type: str = "user"


@dataclass
class Config:
    """Scrinium global configuration built by :func:`load_config`.

    Attributes:
        paths: File path configuration.
        ingest: Ingestion pipeline configuration.
        search: Full-text search configuration.
        log: Logging and metrics configuration.
        zotero: Zotero integration configuration.
    """

    paths: PathsConfig = field(default_factory=PathsConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    log: LogConfig = field(default_factory=LogConfig)
    zotero: ZoteroConfig = field(default_factory=ZoteroConfig)

    # Root directory of the config file (used to resolve relative paths)
    _root: Path = field(default_factory=Path.cwd, repr=False, compare=False)

    @property
    def papers_dir(self) -> Path:
        """Absolute path to the ingested papers directory."""
        return (self._root / self.paths.papers_dir).resolve()

    @property
    def index_db(self) -> Path:
        """Absolute path to the SQLite index database."""
        return (self._root / self.paths.index_db).resolve()

    @property
    def log_file(self) -> Path:
        """Absolute path to the log file."""
        return (self._root / self.log.file).resolve()

    @property
    def metrics_db_path(self) -> Path:
        """Absolute path to the metrics database."""
        return (self._root / self.log.metrics_db).resolve()

    @property
    def workspace_dir(self) -> Path:
        """Absolute path to the workspace root directory."""
        return (self._root / "workspace").resolve()

    def ensure_dirs(self) -> None:
        """Create runtime directories (data/papers, data/inbox, data/pending, workspace, etc.)."""
        for d in (
            self.papers_dir,
            self._root / "data" / "inbox",
            self._root / "data" / "inbox-proceedings",
            self._root / "data" / "inbox-thesis",
            self._root / "data" / "inbox-patent",
            self._root / "data" / "inbox-doc",
            self._root / "data" / "pending",
            self._root / "data" / "proceedings",
            self.workspace_dir,
            self.log_file.parent,
            self.metrics_db_path.parent,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def resolved_zotero_api_key(self) -> str:
        """Resolve the Zotero API key.

        Order: config ``zotero.api_key`` -> ``ZOTERO_API_KEY`` environment variable.

        Returns:
            API key string, or empty string if unset.
        """
        if self.zotero.api_key:
            return self.zotero.api_key
        return os.environ.get("ZOTERO_API_KEY", "")

    def resolved_zotero_library_id(self) -> str:
        """Resolve the Zotero library ID.

        Order: config ``zotero.library_id`` -> ``ZOTERO_LIBRARY_ID`` environment variable.

        Returns:
            Library ID string, or empty string if unset.
        """
        if self.zotero.library_id:
            return self.zotero.library_id
        return os.environ.get("ZOTERO_LIBRARY_ID", "")

    def resolved_mineru_api_key(self) -> str:
        """Resolve the MinerU API token.

        Order: config ``ingest.mineru_api_key`` -> ``MINERU_TOKEN`` ->
        legacy ``MINERU_API_KEY`` environment variable.

        Returns:
            Token string, or empty string if unset.
        """
        if self.ingest.mineru_api_key:
            return self.ingest.mineru_api_key
        return os.environ.get("MINERU_TOKEN", "") or os.environ.get("MINERU_API_KEY", "")

    def resolved_s2_api_key(self) -> str:
        """Resolve the Semantic Scholar API key.

        Order: config ``ingest.s2_api_key`` -> ``S2_API_KEY`` environment variable.

        Returns:
            API key string, or empty string if unset.
        """
        if self.ingest.s2_api_key:
            return self.ingest.s2_api_key
        return os.environ.get("S2_API_KEY", "")

    def resolved_openalex_api_key(self) -> str:
        """Resolve the OpenAlex API key.

        Order: config ``ingest.openalex_api_key`` -> ``OPENALEX_API_KEY`` environment variable.

        Returns:
            API key string, or empty string if unset.
        """
        if self.ingest.openalex_api_key:
            return self.ingest.openalex_api_key
        return os.environ.get("OPENALEX_API_KEY", "")


# ============================================================================
#  Loading
# ============================================================================


def load_config(config_path: Path | None = None) -> Config:
    """Load and merge YAML configuration files.

    ``config.yaml`` provides the base; ``config.local.yaml`` overrides matching keys.

    Args:
        config_path: Optional config file path. When ``None``, checks
            ``SCRINIUM_CONFIG`` (legacy ``SCHOLARAIO_CONFIG``), walks up to 6
            directories from cwd, then checks the global config directory.

    Returns:
        Merged :class:`Config` instance.
    """
    if config_path is None:
        env_path = _env_with_fallback("SCRINIUM_CONFIG")
        if env_path:
            config_path = Path(env_path)
        else:
            config_path = _find_config_file()

    data: dict = {}
    root = Path.cwd()

    if config_path and config_path.exists():
        root = config_path.parent
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # config.local.yaml overrides config.yaml
        local_path = config_path.parent / "config.local.yaml"
        if local_path.exists():
            with open(local_path, encoding="utf-8") as f:
                local_data = yaml.safe_load(f) or {}
            data = _deep_merge(data, local_data)

    return _build_config(data, root)


def _find_config_file() -> Path | None:
    """Walk up from cwd to find config.yaml, then try ~/.scrinium/."""
    # 1. Walk up from cwd (max 6 levels)
    current = Path.cwd()
    for _ in range(6):
        candidate = current / "config.yaml"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    # 2. Global fallback: ~/.scrinium/config.yaml (plugin mode); the legacy
    #    pre-fork ~/.scholaraio/config.yaml is honored with a migration warning.
    try:
        global_cfg = Path.home() / ".scrinium" / "config.yaml"
        if global_cfg.exists():
            return global_cfg
        legacy_cfg = Path.home() / ".scholaraio" / "config.yaml"
        if legacy_cfg.exists():
            _log.warning(
                "found legacy global config %s; consider migrating it to %s",
                legacy_cfg,
                global_cfg,
            )
            return legacy_cfg
    except (RuntimeError, OSError):
        pass
    return None


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base (override wins)."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _bool_or_default(value: object, default: bool) -> bool:
    """Return ``default`` for ``None``; otherwise coerce common bool-like values."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off"}:
            return False
    return bool(value)


def _normalize_choice(value: object, *, default: str, valid: set[str], field_name: str) -> str:
    """Normalize a string choice with safe fallback."""
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text in valid:
        return text
    _log.warning("invalid %s=%r, fallback to %s", field_name, value, default)
    return default


def _normalize_mineru_pdf_cloud_model_version(value: object) -> str:
    """Normalize MinerU cloud model_version for Scrinium's PDF-only ingest flow."""
    raw_text = str(value or "").strip()
    if not raw_text:
        return "pipeline"
    text = raw_text.lower()
    if text == "mineru-html":
        _log.warning("MinerU-HTML is for HTML parsing, not PDF ingest; fallback to pipeline")
        return "pipeline"
    valid_versions = {version.lower() for version in VALID_PDF_CLOUD_MODEL_VERSIONS}
    if text in valid_versions:
        return text
    _log.warning("invalid ingest.mineru_model_version_cloud=%r, fallback to pipeline", value)
    return "pipeline"


def _normalize_mineru_lang(value: object) -> str:
    """Normalize MinerU language with a safe default."""
    text = str(value or "").strip().lower()
    return text or "ch"


def _normalize_mineru_batch_size(value: object) -> int:
    """Normalize MinerU cloud batch size to the official 1-200 range."""
    try:
        size = int(str(value or 20).strip())
    except (TypeError, ValueError):
        _log.warning("invalid ingest.mineru_batch_size=%r, fallback to 20", value)
        return 20
    if size <= 0:
        return 20
    if size > 200:
        _log.warning("ingest.mineru_batch_size=%s exceeds MinerU limit 200, clamp to 200", size)
        return 200
    return size


def _normalize_positive_int(value: object, *, default: int, field_name: str, minimum: int = 1) -> int:
    """Normalize a positive integer config field."""
    try:
        parsed = int(str(value if value is not None else default).strip())
    except (TypeError, ValueError):
        _log.warning("invalid %s=%r, fallback to %s", field_name, value, default)
        return default
    if parsed < minimum:
        return default
    return parsed


# Deprecated config sections removed from the framework (no in-framework
# LLM/embedding calls remain). Each section warns at most once per process.
_DEPRECATED_SECTIONS = ("llm", "translate", "embed", "topics")
_warned_deprecated: set[str] = set()


def _warn_deprecated_sections(data: dict) -> None:
    """Log a one-time deprecation warning for removed config sections.

    Detects top-level ``llm:``/``translate:``/``embed:``/``topics:`` sections,
    a non-regex ``ingest.extractor`` value, and ``ingest.abstract_llm_mode``;
    all are ignored.
    """
    for section in _DEPRECATED_SECTIONS:
        if section in data and section not in _warned_deprecated:
            _warned_deprecated.add(section)
            _log.warning(
                "config section %r is deprecated and ignored: in-framework LLM/embedding calls were removed; "
                "agent skills take over these tasks",
                section,
            )
    ingest_data = data.get("ingest") or {}
    extractor = str(ingest_data.get("extractor", "") or "").strip().lower()
    if extractor and extractor != "regex" and "ingest.extractor" not in _warned_deprecated:
        _warned_deprecated.add("ingest.extractor")
        _log.warning(
            "config ingest.extractor=%r is deprecated and ignored: metadata extraction is regex-only; "
            "low-confidence items go to pending for agent review",
            extractor,
        )
    if "abstract_llm_mode" in ingest_data and "ingest.abstract_llm_mode" not in _warned_deprecated:
        _warned_deprecated.add("ingest.abstract_llm_mode")
        _log.warning(
            "config ingest.abstract_llm_mode=%r is deprecated and ignored: abstract extraction is regex-only; "
            "regex misses are backfilled by the agent",
            ingest_data.get("abstract_llm_mode"),
        )


def _build_config(data: dict, root: Path) -> Config:
    """Build Config dataclass from raw dict."""
    _warn_deprecated_sections(data)

    paths_data = data.get("paths", {}) or {}
    ingest_data = data.get("ingest", {}) or {}

    paths = PathsConfig(
        papers_dir=paths_data.get("papers_dir", "data/papers"),
        index_db=paths_data.get("index_db", "data/index.db"),
    )

    ingest = IngestConfig(
        mineru_endpoint=ingest_data.get("mineru_endpoint", "http://localhost:8000"),
        mineru_cloud_url=ingest_data.get("mineru_cloud_url", "https://mineru.net/api/v4"),
        mineru_api_key=ingest_data.get("mineru_api_key") or "",
        mineru_backend_local=_normalize_choice(
            ingest_data.get("mineru_backend_local", "pipeline"),
            default="pipeline",
            valid=VALID_LOCAL_MINERU_BACKENDS,
            field_name="ingest.mineru_backend_local",
        ),
        mineru_model_version_cloud=_normalize_mineru_pdf_cloud_model_version(
            ingest_data.get("mineru_model_version_cloud", "pipeline")
        ),
        mineru_lang=_normalize_mineru_lang(ingest_data.get("mineru_lang", "ch")),
        mineru_parse_method=_normalize_choice(
            ingest_data.get("mineru_parse_method", "auto"),
            default="auto",
            valid=VALID_MINERU_PARSE_METHODS,
            field_name="ingest.mineru_parse_method",
        ),
        mineru_enable_formula=_bool_or_default(ingest_data.get("mineru_enable_formula"), True),
        mineru_enable_table=_bool_or_default(ingest_data.get("mineru_enable_table"), True),
        contact_email=ingest_data.get("contact_email") or "",
        s2_api_key=ingest_data.get("s2_api_key") or "",
        openalex_api_key=ingest_data.get("openalex_api_key") or "",
        mineru_batch_size=_normalize_mineru_batch_size(ingest_data.get("mineru_batch_size")),
        mineru_upload_workers=_normalize_positive_int(
            ingest_data.get("mineru_upload_workers"),
            default=4,
            field_name="ingest.mineru_upload_workers",
        ),
        mineru_upload_retries=_normalize_positive_int(
            ingest_data.get("mineru_upload_retries"),
            default=3,
            field_name="ingest.mineru_upload_retries",
        ),
        mineru_download_retries=_normalize_positive_int(
            ingest_data.get("mineru_download_retries"),
            default=3,
            field_name="ingest.mineru_download_retries",
        ),
        mineru_poll_timeout=_normalize_positive_int(
            ingest_data.get("mineru_poll_timeout"),
            default=900,
            field_name="ingest.mineru_poll_timeout",
            minimum=60,
        ),
        enrich_timeout=_normalize_positive_int(
            ingest_data.get("enrich_timeout"),
            default=180,
            field_name="ingest.enrich_timeout",
            minimum=30,
        ),
        chunk_page_limit=int(ingest_data.get("chunk_page_limit") or 100),
        pdf_preferred_parser=_normalize_choice(
            ingest_data.get("pdf_preferred_parser", "mineru"),
            default="mineru",
            valid=VALID_PDF_PREFERRED_PARSERS,
            field_name="ingest.pdf_preferred_parser",
        ),
        pdf_fallback_order=_coerce_str_list(ingest_data.get("pdf_fallback_order"), default=["auto"]),
        pdf_fallback_auto_detect=_bool_or_default(ingest_data.get("pdf_fallback_auto_detect"), True),
    )

    search_data = data.get("search", {}) or {}
    search = SearchConfig(
        top_k=int(search_data.get("top_k", 20)),
    )

    log_data = data.get("logging", {}) or {}
    log = LogConfig(
        level=log_data.get("level", "INFO"),
        file=log_data.get("file", "data/scrinium.log"),
        max_bytes=int(log_data.get("max_bytes", 10_000_000)),
        backup_count=int(log_data.get("backup_count", 3)),
        metrics_db=log_data.get("metrics_db", "data/metrics.db"),
    )

    zotero_data = data.get("zotero", {}) or {}
    zotero = ZoteroConfig(
        api_key=zotero_data.get("api_key") or "",
        library_id=str(zotero_data.get("library_id") or ""),
        library_type=zotero_data.get("library_type", "user"),
    )

    return Config(
        paths=paths,
        ingest=ingest,
        search=search,
        log=log,
        zotero=zotero,
        _root=root,
    )


def _coerce_str_list(value, *, default: list[str]) -> list[str]:
    """Normalize config values that accept either a string or a list of strings."""
    if value is None:
        return list(default)
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else list(default)
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            if item is None or not isinstance(item, str):
                continue
            text = item.strip()
            if text:
                result.append(text)
        return result or list(default)
    _log.warning(
        "invalid string-list config value %r (type=%s), fallback to default %r",
        value,
        type(value).__name__,
        default,
    )
    return list(default)

"""
config.py — Scrinium 配置加载
================================

优先级（从高到低）：
  1. config.local.yaml（不进 git，存 API key 等敏感信息）
  2. config.yaml（主配置）
  3. 代码默认值

查找 config.yaml 的路径顺序：
  1. 显式传入的 config_path
  2. 环境变量 SCRINIUM_CONFIG（旧名 SCHOLARAIO_CONFIG 仍兼容，命中时告警）
  3. 当前工作目录逐级向上查找
  4. ~/.scrinium/config.yaml（全局配置，插件模式使用；不存在时兼容读取
     旧的 ~/.scholaraio/config.yaml 并提示迁移）

已移除的配置段（llm/translate/embed/topics）在加载时触发一次性
deprecation warning 并被忽略——框架内不再调用任何 LLM/embedding。
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
    """文件路径配置。

    Attributes:
        papers_dir: 已入库论文目录（相对于项目根目录）。
        index_db: SQLite 索引数据库路径（相对于项目根目录）。
    """

    papers_dir: str = "data/papers"
    index_db: str = "data/index.db"


@dataclass
class SearchConfig:
    """FTS5 全文检索配置。

    Attributes:
        top_k: ``scrinium search`` 默认返回条数。
    """

    top_k: int = 20


@dataclass
class LogConfig:
    """日志与指标配置。

    Attributes:
        level: 根日志级别，``"DEBUG"`` | ``"INFO"`` | ``"WARNING"``。
        file: 日志文件路径（相对于项目根目录）。
        max_bytes: 单个日志文件最大字节数，超出则轮转。
        backup_count: 轮转保留的旧日志文件数。
        metrics_db: 指标数据库路径（相对于项目根目录）。
    """

    level: str = "INFO"
    file: str = "data/scrinium.log"
    max_bytes: int = 10_000_000  # 10 MB
    backup_count: int = 3
    metrics_db: str = "data/metrics.db"


@dataclass
class IngestConfig:
    """数据入库管道配置。

    Attributes:
        mineru_endpoint: MinerU 本地 API 地址。
        mineru_cloud_url: `mineru-open-api` 的 ``--base-url`` 覆盖值。
            默认值保留官方公网地址，私有部署时可改成自建服务。
        mineru_api_key: MinerU token，建议放 config.local.yaml 或环境变量。
            兼容旧字段名；运行时会映射给 ``mineru-open-api`` 的 ``MINERU_TOKEN``。
        mineru_backend_local: 本地 MinerU backend（``pipeline`` | ``vlm-auto-engine`` |
            ``vlm-http-client`` | ``hybrid-auto-engine`` | ``hybrid-http-client``）。
        mineru_model_version_cloud: 云端 PDF 解析 model_version（``pipeline`` | ``vlm``）。
        mineru_lang: MinerU OCR 语言（``ch`` | ``en`` | ``latin`` 等）。
        mineru_parse_method: 解析方式（``auto`` | ``txt`` | ``ocr``）。云端经
            `mineru-open-api` 解析时仅 ``ocr`` 会映射为 ``--ocr`` flag（``txt``
            无对应模式，按默认处理并告警）。
        mineru_enable_formula: 是否启用公式解析。仅对云端 ``pipeline``/``vlm`` 生效。
        mineru_enable_table: 是否启用表格解析。仅对云端 ``pipeline``/``vlm`` 生效。
        contact_email: Crossref polite pool 联系邮箱（User-Agent），建议放 config.local.yaml。
        s2_api_key: Semantic Scholar API 密钥，有 key 可大幅提升限速（1 req/s vs 100 req/5min）。
            建议放 config.local.yaml 或环境变量 ``S2_API_KEY``。
        chunk_page_limit: 本地 MinerU 对超长 PDF 的自动切分页数阈值。超过此值
            的 PDF 在转换前自动拆分为多个短 PDF，转换后合并为单个 Markdown。
            云端 MinerU 另外还会遵循 600 页 / 200MB 的官方单文件限制。
        mineru_batch_size: `mineru-open-api` 兼容层的分块大小，默认 20。
        mineru_upload_workers: 云端 CLI / `mineru-open-api` 兼容层的并发配置。
            对分块后的云端转换仍生效，用于限制同时进行的转换任务数。
        mineru_upload_retries: 云端 `mineru-open-api` 单文件重试次数（含首轮），
            默认 3。当前用于 MinerU cloud CLI 的指数退避重试。
        mineru_download_retries: 旧云 API 下载重试配置；为兼容保留。
        mineru_poll_timeout: `mineru-open-api` 单次转换超时（秒），默认 900。
        pdf_preferred_parser: 首选 PDF 解析器。默认优先 ``mineru``，也可显式设为
            ``docling`` 或 ``pymupdf`` 跳过 MinerU。
        pdf_fallback_order: MinerU 不可用或解析失败时的替代解析器顺序。
            支持 ``docling`` / ``pymupdf`` / ``auto``。
        pdf_fallback_auto_detect: 是否启用自动检测本机已安装的 fallback 解析器。
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
    chunk_page_limit: int = 100  # local MinerU auto-split threshold in pages
    mineru_batch_size: int = 20  # cloud batch size per request
    mineru_upload_workers: int = 4
    mineru_upload_retries: int = 3
    mineru_download_retries: int = 3
    mineru_poll_timeout: int = 900
    pdf_preferred_parser: str = "mineru"
    pdf_fallback_order: list[str] = field(default_factory=lambda: ["auto"])
    pdf_fallback_auto_detect: bool = True


@dataclass
class ZoteroConfig:
    """Zotero 集成配置。

    Attributes:
        api_key: Zotero Web API 密钥。
        library_id: Zotero 用户/群组 library ID。
        library_type: Library 类型，``"user"`` 或 ``"group"``。
    """

    api_key: str = ""
    library_id: str = ""
    library_type: str = "user"


@dataclass
class Config:
    """Scrinium 全局配置，由 :func:`load_config` 构建。

    Attributes:
        paths: 文件路径配置。
        ingest: 数据入库配置。
        search: 全文检索配置。
        log: 日志与指标配置。
        zotero: Zotero 集成配置。
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
        """已入库论文目录的绝对路径。"""
        return (self._root / self.paths.papers_dir).resolve()

    @property
    def index_db(self) -> Path:
        """SQLite 索引数据库的绝对路径。"""
        return (self._root / self.paths.index_db).resolve()

    @property
    def log_file(self) -> Path:
        """日志文件的绝对路径。"""
        return (self._root / self.log.file).resolve()

    @property
    def metrics_db_path(self) -> Path:
        """指标数据库的绝对路径。"""
        return (self._root / self.log.metrics_db).resolve()

    @property
    def workspace_dir(self) -> Path:
        """工作区根目录的绝对路径。"""
        return (self._root / "workspace").resolve()

    def ensure_dirs(self) -> None:
        """创建运行所需的目录（data/papers, data/inbox, data/pending, workspace 等）。"""
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
        """按优先级查找 Zotero API key。

        查找顺序: config ``zotero.api_key`` → 环境变量 ``ZOTERO_API_KEY``。

        Returns:
            API key 字符串，未找到则返回空字符串。
        """
        if self.zotero.api_key:
            return self.zotero.api_key
        return os.environ.get("ZOTERO_API_KEY", "")

    def resolved_zotero_library_id(self) -> str:
        """按优先级查找 Zotero library ID。

        查找顺序: config ``zotero.library_id`` → 环境变量 ``ZOTERO_LIBRARY_ID``。

        Returns:
            Library ID 字符串，未找到则返回空字符串。
        """
        if self.zotero.library_id:
            return self.zotero.library_id
        return os.environ.get("ZOTERO_LIBRARY_ID", "")

    def resolved_mineru_api_key(self) -> str:
        """按优先级查找 MinerU token。

        查找顺序:
        config ``ingest.mineru_api_key`` → 环境变量 ``MINERU_TOKEN`` →
        环境变量 ``MINERU_API_KEY``（旧兼容名）。

        Returns:
            token 字符串，未找到则返回空字符串。
        """
        if self.ingest.mineru_api_key:
            return self.ingest.mineru_api_key
        return os.environ.get("MINERU_TOKEN", "") or os.environ.get("MINERU_API_KEY", "")

    def resolved_s2_api_key(self) -> str:
        """按优先级查找 Semantic Scholar API key。

        查找顺序: config ``ingest.s2_api_key`` → 环境变量 ``S2_API_KEY``。

        Returns:
            API key 字符串，未找到则返回空字符串。
        """
        if self.ingest.s2_api_key:
            return self.ingest.s2_api_key
        return os.environ.get("S2_API_KEY", "")


# ============================================================================
#  Loading
# ============================================================================


def load_config(config_path: Path | None = None) -> Config:
    """加载并合并 YAML 配置文件。

    合并策略: ``config.yaml`` 为基础，``config.local.yaml`` 覆盖同名字段。

    Args:
        config_path: 配置文件路径。为 ``None`` 时依次查找环境变量
            ``SCRINIUM_CONFIG``（旧名 ``SCHOLARAIO_CONFIG`` 兼容）、
            当前目录向上最多 6 级的 ``config.yaml``。

    Returns:
        合并后的 :class:`Config` 实例。
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

    Detects top-level ``llm:``/``translate:``/``embed:``/``topics:`` sections
    and a non-regex ``ingest.extractor`` value; all are ignored.
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

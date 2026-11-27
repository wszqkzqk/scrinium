"""
setup.py - Scrinium environment checks and interactive setup wizard.

Modes:
  scrinium setup          Interactive setup wizard
  scrinium setup check    Environment status diagnostics
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.metadata
import importlib.util
import io
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from scrinium.config import Config, load_config

# ============================================================================
#  Bilingual strings
# ============================================================================

# User-facing strings (English)
_S: dict[str, str] = {
    "python_ver": "Python version",
    "core_deps": "Core deps",
    "import_deps": "Import deps",
    "pdf_deps": "PDF deps",
    "office_deps": "Office deps",
    "draw_deps": "Draw deps",
    "config_yaml": "config.yaml",
    "mineru": "MinerU",
    "docling": "Docling",
    "huggingface": "Hugging Face",
    "parser_recommendation": "PDF parser recommendation",
    "contact_email": "Contact email",
    "s2_key": "Semantic Scholar API key",
    "openalex_key": "OpenAlex API key",
    "zotero_key": "Zotero API key",
    "directories": "Directories",
    "papers_count": "Papers",
    "optional_s2_set": "configured ({masked}) | optional: authenticated access; some endpoints require a key",
    "optional_s2_unset": "not set | optional: most endpoints work anonymously; some require a key",
    "optional_openalex_set": "configured ({masked}) | optional: raises the OpenAlex daily API budget",
    "optional_openalex_unset": "not set | optional: raises the daily API quota",
    "optional_zotero_set": "configured ({masked}) | optional: used by Zotero Web API import",
    "optional_zotero_unset": "not set | optional: required for Zotero Web API import only (not local zotero.sqlite)",
    "installed": "installed",
    "not_installed": "not installed",
    "found": "found",
    "not_found": "not found",
    "configured": "configured",
    "not_set": "not set",
    "all_ok": "all exist",
    "welcome": "\n=== Scrinium Setup Wizard ===\n",
    "step_deps": "Step 1: Checking dependencies...",
    "step_config": "Step 2: Configuration file",
    "step_parser": "Step 3: Choose a PDF parser",
    "step_keys_followup": "Step 4: API keys (stored in config.local.yaml, not tracked by git)",
    "step_verify": "Step 5: Verification",
    "install_prompt": "  {group} deps missing: {pkgs}\n  Install? ({cmd})",
    "yn": " [Y/n] ",
    "skip": "  Skipped.",
    "installing": "  Installing {group}...",
    "install_ok": "  Installed successfully.",
    "install_fail": "  Installation failed. You can install later with: {cmd}",
    "config_exists": "  config.yaml already exists, skipping.",
    "config_created": "  Created config.yaml with default settings.",
    "mineru_key_prompt": "  MinerU token for `mineru-open-api extract` (free to apply at https://mineru.net/apiManage/token).\n  Without it: Scrinium can still use local MinerU / Docling / PyMuPDF, but precise MinerU cloud parsing is unavailable.\n  Press Enter to skip.",
    "parser_choice_prompt": "  Which PDF parser do you want to use?\n  1. MinerU\n  2. Docling\n  3. Not sure, test and recommend for me",
    "parser_choice_mineru": "  Selected MinerU.",
    "parser_choice_docling": "  Selected Docling.",
    "parser_choice_auto": "  Testing MinerU availability and Hugging Face reachability...",
    "parser_choice_auto_configured_mineru": "  MinerU token found; skipping network probe.",
    "parser_choice_auto_token_without_cli": "  MinerU token found, but `mineru-open-api` is missing; run `pip install mineru-open-api` first.",
    "parser_choice_auto_cli_without_token": "  MinerU CLI found, but no token configured; add a free token later for cloud mode.",
    "reachability_yes": "reachable",
    "reachability_no": "unreachable",
    "availability_yes": "available",
    "availability_no": "unavailable",
    "parser_recommend_mineru": "  Recommended: MinerU ({reason})",
    "parser_recommend_docling": "  Recommended: Docling ({reason})",
    "parser_recommend_override": "  You can still choose the other parser.",
    "reason_mineru_only": "MinerU is available while Hugging Face is not reachable.",
    "reason_hf_only": "Hugging Face is reachable while MinerU is not available.",
    "reason_both": "MinerU is available and Hugging Face is also reachable; prefer MinerU by default.",
    "reason_neither": "MinerU and Hugging Face are unreachable; Docling runs locally without MinerU.",
    "mineru_local_prompt": "  Do you plan to deploy MinerU locally?",
    "mineru_cloud_note": "  If not deploying locally, register for a free MinerU API key.",
    "docling_guide_title": "  Docling local deployment guide:",
    "mineru_guide_title": "  MinerU local deployment guide:",
    "docling_guide_body": "    1. Official install docs: https://docling-project.github.io/docling/getting_started/installation/\n    2. Official CLI docs: https://docling-project.github.io/docling/reference/cli/\n    3. GitHub: https://github.com/docling-project/docling\n    4. Quick start: pip install docling\n    5. CPU-only Linux example: pip install docling --extra-index-url https://download.pytorch.org/whl/cpu\n    6. After install, verify with: docling --help",
    "mineru_guide_body": "    1. Official quick start: https://opendatalab.github.io/MinerU/quick_start/\n    2. Official Docker deployment: https://opendatalab.github.io/MinerU/quick_start/docker_deployment/\n    3. Official usage docs: https://opendatalab.github.io/MinerU/usage/quick_usage/\n    4. GitHub: https://github.com/opendatalab/MinerU\n    5. For local models, MinerU docs describe `mineru-models-download` and `mineru -p <input> -o <output> --source local`\n    6. If Hugging Face is blocked, MinerU docs suggest switching model source to ModelScope",
    "email_prompt": "  Contact email (free, for the Crossref polite pool).\n  Press Enter to skip.",
    "key_saved": "  Saved to config.local.yaml.",
    "no_keys": "  No keys configured. You can add them later in config.local.yaml.",
    "config_unchanged": "  No changes; kept existing config.local.yaml.",
    "import_hint": "\nTip: To import papers from Zotero or Endnote, use:\n  scrinium import-endnote <xml-or-ris-file>\n  scrinium import-zotero --library-id <ID> --api-key <API_KEY> --collection <COLLECTION_KEY>\n  scrinium import-zotero --local /path/to/zotero.sqlite\n",
    "done": "\nSetup complete! Put papers in data/inbox/ and run:\n  scrinium pipeline ingest\n",
}

MINERU_TOKEN_URL = "https://mineru.net/apiManage/token"
MINERU_DOCS_URL = "https://opendatalab.github.io/MinerU/quick_start/"
MINERU_DOCKER_URL = "https://opendatalab.github.io/MinerU/quick_start/docker_deployment/"
DOCLING_INSTALL_URL = "https://docling-project.github.io/docling/getting_started/installation/"
DOCLING_CLI_URL = "https://docling-project.github.io/docling/reference/cli/"
HUGGINGFACE_URL = "https://huggingface.co"
DEFAULT_PDF_PARSER = "mineru"


def t(key: str) -> str:
    """Return the UI string for *key*."""
    return _S.get(key, key)


@dataclass
class PromptResult:
    text: str
    from_eof: bool = False


@dataclass
class MinerUStatus:
    ok: bool
    detail: str
    recommendable: bool
    cloud_only: bool
    cli_available: bool
    token_configured: bool


def _prompt_result(prompt: str) -> PromptResult:
    """Read one prompt and preserve whether EOF was hit."""
    try:
        return PromptResult(input(prompt).strip(), from_eof=False)
    except (EOFError, StopIteration):
        return PromptResult("", from_eof=True)


def _prompt_text(prompt: str) -> str:
    """Read one line of user input, treating EOF as empty input.

    This keeps setup usable when driven by agents or piped stdin where the
    input stream may end before all optional prompts are answered.
    """
    return _prompt_result(prompt).text


# ============================================================================
#  Dependency checking
# ============================================================================

# (import_name, pip_name)
_DEP_GROUPS: dict[str, list[tuple[str, str]]] = {
    "core": [("requests", "requests"), ("yaml", "pyyaml"), ("mineru_open_api", "mineru-open-api")],
    "import": [("endnote_utils", "endnote-utils"), ("pyzotero", "pyzotero")],
    "pdf": [("fitz", "pymupdf")],
    "office": [
        ("markitdown", "markitdown[docx,pptx,xlsx]"),
        ("docx", "python-docx"),
        ("pptx", "python-pptx"),
        ("openpyxl", "openpyxl"),
    ],
    "draw": [("mermaid", "mermaid-py"), ("cli_anything", "cli-anything-inkscape")],
}


@dataclass
class DepGroupStatus:
    """Dependency group check result."""

    name: str
    installed: bool
    missing: list[str] = field(default_factory=list)


def check_dep_group(group: str) -> DepGroupStatus:
    """Check if all packages in a dependency group are importable.

    Args:
        group: Dependency group name (core/import/pdf/office/draw).

    Returns:
        DepGroupStatus with installed flag and list of missing pip package names.
    """
    pairs = _DEP_GROUPS.get(group, [])
    missing = []
    for import_name, pip_name in pairs:
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                importlib.import_module(import_name)
        except Exception:
            missing.append(pip_name)
    return DepGroupStatus(name=group, installed=not missing, missing=missing)


def _editable_project_root() -> Path | None:
    """Return the source checkout root when scrinium is an editable install.

    Inspects ``direct_url.json`` across all installed scrinium distributions
    (a stale ``*.egg-info`` earlier on sys.path can shadow the real dist-info,
    so a single ``distribution()`` lookup is not enough).

    Returns:
        Checkout root containing ``pyproject.toml``, or ``None`` for regular
        (site-packages / PyPI) installs.
    """
    try:
        for dist in importlib.metadata.distributions():
            if (dist.metadata["Name"] or "").lower() != "scrinium":
                continue
            direct_url_text = dist.read_text("direct_url.json")
            if not direct_url_text:
                continue
            try:
                data = json.loads(direct_url_text)
            except ValueError:
                continue
            if not (data.get("dir_info") or {}).get("editable"):
                continue
            root = Path(__file__).resolve().parent.parent
            return root if (root / "pyproject.toml").exists() else None
    except Exception:
        pass
    return None


# ============================================================================
#  Status checks
# ============================================================================


@dataclass
class CheckResult:
    """Single check result."""

    label: str
    ok: bool
    detail: str


@dataclass
class ParserChoice:
    """Result of parser selection in setup wizard."""

    parser: str
    needs_mineru_key: bool = False


def run_check(cfg: Config | None = None) -> list[CheckResult]:
    """Run all environment checks.

    Args:
        cfg: Config instance. If None, loads default config.

    Returns:
        List of CheckResult items.
    """
    if cfg is None:
        cfg = load_config()

    results: list[CheckResult] = []

    # Python version
    vi = sys.version_info
    ver_str = f"{vi.major}.{vi.minor}.{vi.micro}"
    results.append(
        CheckResult(
            label=t("python_ver"),
            ok=vi >= (3, 10),
            detail=ver_str + (" ✓" if vi >= (3, 10) else " (need ≥3.10)"),
        )
    )

    # Dependency groups
    for group, label_key in [
        ("core", "core_deps"),
        ("import", "import_deps"),
        ("pdf", "pdf_deps"),
        ("office", "office_deps"),
        ("draw", "draw_deps"),
    ]:
        status = check_dep_group(group)
        if status.installed:
            pkgs = ", ".join(p for _, p in _DEP_GROUPS[group])
            results.append(CheckResult(t(label_key), True, pkgs))
        else:
            hint = f"pip install scrinium[{group}]"
            results.append(
                CheckResult(
                    t(label_key),
                    False,
                    f"{t('not_installed')}: {', '.join(status.missing)}  → {hint}",
                )
            )

    # config.yaml
    root = cfg._root
    config_path = root / "config.yaml"
    results.append(
        CheckResult(
            t("config_yaml"),
            config_path.exists(),
            t("found") if config_path.exists() else t("not_found"),
        )
    )

    # MinerU
    mineru_status = _detect_mineru(cfg)
    results.append(CheckResult(t("mineru"), mineru_status.ok, mineru_status.detail))
    docling_ok, docling_detail = _check_docling()
    results.append(CheckResult(t("docling"), docling_ok, docling_detail))
    hf_ok, hf_detail = _check_huggingface()
    results.append(CheckResult(t("huggingface"), hf_ok, hf_detail))
    parser_name, reason = recommend_pdf_parser(mineru_status.recommendable, hf_ok)
    results.append(CheckResult(t("parser_recommendation"), True, f"{parser_name}: {reason}"))

    # Contact email
    email = cfg.ingest.contact_email
    if email:
        results.append(CheckResult(t("contact_email"), True, email))
    else:
        results.append(CheckResult(t("contact_email"), False, t("not_set")))

    s2_key = cfg.resolved_s2_api_key()
    if s2_key:
        masked = s2_key[:3] + "***" + s2_key[-3:] if len(s2_key) > 8 else "***"
        results.append(
            CheckResult(
                t("s2_key"),
                True,
                t("optional_s2_set").format(masked=masked),
            )
        )
    else:
        results.append(
            CheckResult(
                t("s2_key"),
                True,
                t("optional_s2_unset"),
            )
        )

    openalex_key = cfg.resolved_openalex_api_key()
    if openalex_key:
        masked = openalex_key[:3] + "***" + openalex_key[-3:] if len(openalex_key) > 8 else "***"
        results.append(
            CheckResult(
                t("openalex_key"),
                True,
                t("optional_openalex_set").format(masked=masked),
            )
        )
    else:
        results.append(
            CheckResult(
                t("openalex_key"),
                True,
                t("optional_openalex_unset"),
            )
        )

    zotero_key = cfg.resolved_zotero_api_key()
    if zotero_key:
        masked = zotero_key[:3] + "***" + zotero_key[-3:] if len(zotero_key) > 8 else "***"
        results.append(
            CheckResult(
                t("zotero_key"),
                True,
                t("optional_zotero_set").format(masked=masked),
            )
        )
    else:
        results.append(
            CheckResult(
                t("zotero_key"),
                True,
                t("optional_zotero_unset"),
            )
        )

    # Directories
    dirs_to_check = [
        cfg.papers_dir,
        cfg._root / "data" / "inbox",
        cfg._root / "data" / "pending",
        cfg._root / "workspace",
    ]
    missing_dirs = [str(d) for d in dirs_to_check if not d.exists()]
    if missing_dirs:
        results.append(
            CheckResult(
                t("directories"),
                False,
                f"{t('not_found')}: {', '.join(missing_dirs)}",
            )
        )
    else:
        results.append(CheckResult(t("directories"), True, t("all_ok")))

    # Papers count
    papers_dir = cfg.papers_dir
    count = 0
    if papers_dir.exists():
        count = sum(1 for d in papers_dir.iterdir() if d.is_dir() and (d / "meta.json").exists())
    results.append(CheckResult(t("papers_count"), True, str(count)))

    return results


def _detect_mineru(cfg: Config) -> MinerUStatus:
    """Collect MinerU status for both diagnostics and recommendation logic."""
    cli_path = shutil.which("mineru-open-api")
    token_configured = bool(cfg.resolved_mineru_api_key())

    try:
        import requests as _req

        r = _req.get(cfg.ingest.mineru_endpoint, timeout=2)
        if r.status_code < 500:
            return MinerUStatus(
                ok=True,
                detail=f"local server @ {cfg.ingest.mineru_endpoint}",
                recommendable=True,
                cloud_only=False,
                cli_available=bool(cli_path),
                token_configured=token_configured,
            )
    except Exception:
        pass

    if token_configured and cli_path:
        return MinerUStatus(
            ok=True,
            detail=f"mineru-open-api @ {cli_path} + token " + t("configured"),
            recommendable=True,
            cloud_only=True,
            cli_available=True,
            token_configured=True,
        )

    if cli_path and not token_configured:
        detail = (
            f"detected mineru-open-api @ {cli_path}; prefer MinerU. "
            f"Register the free token for cloud mode: {MINERU_TOKEN_URL}"
        )
        return MinerUStatus(
            ok=False,
            detail=detail,
            recommendable=True,
            cloud_only=True,
            cli_available=True,
            token_configured=False,
        )

    if token_configured and not cli_path:
        detail = (
            "MinerU token configured, but mineru-open-api is not installed"
            f" → pip install mineru-open-api | local docs: {MINERU_DOCS_URL} | Docker: {MINERU_DOCKER_URL}"
        )
        return MinerUStatus(
            ok=False,
            detail=detail,
            recommendable=True,
            cloud_only=True,
            cli_available=False,
            token_configured=True,
        )

    detail = (
        "MinerU token / CLI not configured and local MinerU service is unreachable"
        f" → install CLI: pip install mineru-open-api | token: {MINERU_TOKEN_URL} | local docs: {MINERU_DOCS_URL} | Docker: {MINERU_DOCKER_URL}"
    )
    return MinerUStatus(
        ok=False,
        detail=detail,
        recommendable=False,
        cloud_only=False,
        cli_available=False,
        token_configured=False,
    )


def _check_docling() -> tuple[bool, str]:
    """Check whether Docling CLI is installed locally."""
    cmd = shutil.which("docling")
    if cmd:
        return True, cmd
    return False, f"not installed → pip install docling | install docs: {DOCLING_INSTALL_URL} | CLI: {DOCLING_CLI_URL}"


def _probe_url(url: str, timeout: int = 2) -> bool:
    """Return whether a URL is reachable with a lightweight GET request."""
    try:
        import requests as _req

        r = _req.get(url, timeout=timeout, allow_redirects=True)
        return r.status_code < 500
    except Exception:
        return False


def _check_huggingface() -> tuple[bool, str]:
    """Check whether Hugging Face is reachable from current network."""
    ok = _probe_url(HUGGINGFACE_URL)
    if ok:
        return True, t("reachability_yes")
    return False, "unreachable → Docling or Hugging Face model downloads may fail; prefer MinerU / ModelScope"


def _wizard_mineru_available(cfg: Config) -> tuple[bool, bool]:
    """Detect MinerU availability for setup wizard auto recommendation.

    Returns:
        A tuple of ``(available, cloud_only)`` where ``cloud_only`` means the
        detected path requires a MinerU token instead of local deployment.
    """
    status = _detect_mineru(cfg)
    return status.recommendable, status.cloud_only


def recommend_pdf_parser(mineru_available: bool, huggingface_reachable: bool) -> tuple[str, str]:
    """Recommend MinerU or Docling from availability signals.

    Args:
        mineru_available: Whether MinerU is usable in the current setup flow.
            This can come from an existing cloud key, a reachable local service,
            or a lightweight heuristic used by the setup wizard.
        huggingface_reachable: Whether Hugging Face is reachable from the
            current network.

    Returns:
        A tuple of ``(recommended_parser, reason)``.
    """
    if mineru_available and not huggingface_reachable:
        return "MinerU", t("reason_mineru_only")
    if huggingface_reachable and not mineru_available:
        return "Docling", t("reason_hf_only")
    if mineru_available and huggingface_reachable:
        return "MinerU", t("reason_both")
    return "Docling", t("reason_neither")


def format_check_results(results: list[CheckResult]) -> str:
    """Format check results as a readable table.

    Args:
        results: List of CheckResult from run_check().

    Returns:
        Formatted string with [OK]/[--] prefixes.
    """
    lines = []
    max_label = max(len(r.label) for r in results) if results else 0
    for r in results:
        mark = "[OK]" if r.ok else "[--]"
        lines.append(f"  {mark} {r.label:<{max_label}}  {r.detail}")
    return "\n".join(lines)


# ============================================================================
#  Interactive wizard
# ============================================================================


def run_wizard(cfg: Config | None = None) -> None:
    """Interactive setup wizard.

    Args:
        cfg: Config instance. If None, loads default config.
    """

    if cfg is None:
        cfg = load_config()
    root = cfg._root

    print(t("welcome"))

    # Step 1: Dependencies
    print(t("step_deps"))
    _wizard_deps()

    # Step 2: config.yaml
    print(f"\n{t('step_config')}")
    _wizard_config(root)

    # Reload config after generating config.yaml
    cfg = load_config()
    cfg.ensure_dirs()

    # Step 3: PDF parser
    print(f"\n{t('step_parser')}")
    parser_choice = _wizard_parser(cfg)

    # Step 4: API keys
    print(f"\n{t('step_keys_followup')}")
    _wizard_keys(root, parser_choice)

    # Import hint
    print(t("import_hint"))

    # Step 5: Verify
    print(f"{t('step_verify')}")
    cfg = load_config()  # reload with new keys
    results = run_check(cfg)
    print(format_check_results(results))

    print(t("done"))


def _wizard_deps() -> None:
    """Check and optionally install missing dependency groups."""
    editable_root = _editable_project_root()
    for group in ("core", "import", "pdf", "office", "draw"):
        status = check_dep_group(group)
        label_key = f"{group}_deps"
        if status.installed:
            pkgs = ", ".join(p for _, p in _DEP_GROUPS[group])
            print(f"  [OK] {t(label_key)}: {pkgs}")
        else:
            if editable_root is not None:
                # Editable checkout: install extras from the local tree so pip
                # does not replace it with the PyPI release.
                cmd_hint = f'pip install -e ".[{group}]"'
                run_args = [sys.executable, "-m", "pip", "install", "-e", f".[{group}]"]
            else:
                cmd_hint = f"pip install scrinium[{group}]"
                run_args = [sys.executable, "-m", "pip", "install", f"scrinium[{group}]"]
            msg = t("install_prompt").format(group=group, pkgs=", ".join(status.missing), cmd=cmd_hint)
            print(msg)
            answer = _prompt_result(t("yn"))
            ans = answer.text.lower()
            if answer.from_eof:
                print(t("skip"))
                continue
            if ans in ("", "y", "yes"):
                print(t("installing").format(group=group))
                ret = subprocess.run(
                    run_args,
                    capture_output=True,
                    text=True,
                    cwd=editable_root,
                )
                if ret.returncode == 0:
                    print(t("install_ok"))
                else:
                    print(t("install_fail").format(group=group, cmd=cmd_hint))
                    if ret.stderr:
                        # show last 3 lines of error
                        err_lines = ret.stderr.strip().splitlines()[-3:]
                        for line in err_lines:
                            print(f"    {line}")
            else:
                print(t("skip"))


def _wizard_config(root: Path) -> None:
    """Generate config.yaml if it doesn't exist."""
    config_path = root / "config.yaml"
    if config_path.exists():
        print(t("config_exists"))
        return

    config_path.write_text(_CONFIG_TEMPLATE, encoding="utf-8")
    print(t("config_created"))


def _wizard_parser(cfg: Config) -> ParserChoice:
    """Interactively help the user choose between MinerU and Docling."""
    print(t("parser_choice_prompt"))
    choice = _prompt_text("  > ")
    if choice == "1":
        print(t("parser_choice_mineru"))
        print(t("mineru_cloud_note"))
        use_local = _prompt_yes_no(t("mineru_local_prompt"), default=False)
        print(t("mineru_guide_title"))
        print(t("mineru_guide_body"))
        if use_local:
            return ParserChoice(parser="mineru", needs_mineru_key=False)
        return ParserChoice(parser="mineru", needs_mineru_key=True)
    if choice == "2":
        print(t("parser_choice_docling"))
        print(t("docling_guide_title"))
        print(t("docling_guide_body"))
        return ParserChoice(parser="docling", needs_mineru_key=False)

    print(t("parser_choice_auto"))
    mineru_status = _detect_mineru(cfg)
    mineru_available = mineru_status.recommendable
    if mineru_status.token_configured and not mineru_status.cli_available:
        print(t("parser_choice_auto_token_without_cli"))
    elif mineru_status.cloud_only and mineru_status.token_configured:
        print(t("parser_choice_auto_configured_mineru"))
    elif mineru_status.cloud_only:
        print(t("parser_choice_auto_cli_without_token"))
    hf_ok = _probe_url(HUGGINGFACE_URL)
    print(f"    MinerU: {t('availability_yes') if mineru_available else t('availability_no')}")
    print(f"    Hugging Face: {t('reachability_yes') if hf_ok else t('reachability_no')}")

    parser_name, reason = recommend_pdf_parser(mineru_available, hf_ok)
    if parser_name == "MinerU":
        print(t("parser_recommend_mineru").format(reason=reason))
        print(t("parser_recommend_override"))
        print(t("mineru_cloud_note"))
        use_local = _prompt_yes_no(t("mineru_local_prompt"), default=False)
        print(t("mineru_guide_title"))
        print(t("mineru_guide_body"))
        if use_local:
            return ParserChoice(parser="mineru", needs_mineru_key=False)
        return ParserChoice(parser="mineru", needs_mineru_key=True)

    print(t("parser_recommend_docling").format(reason=reason))
    print(t("parser_recommend_override"))
    print(t("docling_guide_title"))
    print(t("docling_guide_body"))
    return ParserChoice(parser="docling", needs_mineru_key=False)


def _prompt_yes_no(prompt: str, *, default: bool = True) -> bool:
    """Simple bilingual yes/no prompt."""
    suffix = " [Y/n] " if default else " [y/N] "
    answer = _prompt_result(prompt + suffix)
    ans = answer.text.lower()
    if not ans:
        return default
    return ans in ("y", "yes")


def _wizard_keys(root: Path, parser_choice: ParserChoice | None = None) -> None:
    """Interactively configure API keys, write to config.local.yaml."""
    local_path = root / "config.local.yaml"
    local_data: dict = {}
    if local_path.exists():
        local_data_raw = yaml.safe_load(local_path.read_text(encoding="utf-8")) or {}
        if isinstance(local_data_raw, dict):
            local_data = local_data_raw
        else:
            local_data = {}

    changed = False
    ingest_local_raw = local_data.get("ingest")
    ingest_local: dict[str, object] = ingest_local_raw if isinstance(ingest_local_raw, dict) else {}
    if ingest_local_raw is not None and not isinstance(ingest_local_raw, dict):
        changed = True

    if parser_choice is not None:
        existing_parser = ingest_local.get("pdf_preferred_parser")
        desired_parser = parser_choice.parser
        if desired_parser != DEFAULT_PDF_PARSER:
            if existing_parser != desired_parser:
                ingest_local["pdf_preferred_parser"] = desired_parser
                changed = True
        elif "pdf_preferred_parser" in ingest_local:
            ingest_local.pop("pdf_preferred_parser", None)
            changed = True

    # MinerU token
    if parser_choice is None or parser_choice.needs_mineru_key:
        print(t("mineru_key_prompt"))
        key = _prompt_text("  > ")
        if key:
            ingest_local["mineru_api_key"] = key
            changed = True

    # Contact email
    print(t("email_prompt"))
    email = _prompt_text("  > ")
    if email:
        ingest_local["contact_email"] = email
        changed = True

    if ingest_local:
        local_data["ingest"] = ingest_local
    else:
        local_data.pop("ingest", None)

    if changed:
        if local_data:
            local_path.write_text(
                yaml.dump(local_data, allow_unicode=True, default_flow_style=False),
                encoding="utf-8",
            )
            print(t("key_saved"))
        else:
            if local_path.exists():
                local_path.unlink()
            print(t("no_keys"))
    else:
        if local_path.exists():
            print(t("config_unchanged"))
        else:
            print(t("no_keys"))


# ============================================================================
#  Config template
# ============================================================================

_CONFIG_TEMPLATE = """\
# Scrinium configuration
# Sensitive values (API keys) go in config.local.yaml (git-ignored).

paths:
  papers_dir: data/papers
  index_db: data/index.db

# Ingestion pipeline
ingest:
  pdf_preferred_parser: mineru       # mineru | docling | pymupdf
  mineru_endpoint: http://localhost:8000
  mineru_cloud_url: https://mineru.net/api/v4  # mineru-open-api --base-url override for private deployments
  mineru_api_key: null        # MinerU token -> config.local.yaml or env MINERU_TOKEN / MINERU_API_KEY
  mineru_backend_local: pipeline      # local-only backend; keep default unless you self-host MinerU
  mineru_model_version_cloud: pipeline # mineru-open-api extract --model: pipeline | vlm
  mineru_lang: ch                     # keep ch for Chinese/mixed Chinese-English PDFs; switch to en for English-only PDFs
  mineru_parse_method: auto           # auto | txt | ocr; mineru-open-api only maps ocr -> --ocr
  mineru_enable_formula: true         # only effective for pipeline / vlm
  mineru_enable_table: true           # only effective for pipeline / vlm
  contact_email: null       # Crossref polite pool email -> config.local.yaml
  s2_api_key: null          # Semantic Scholar API key -> config.local.yaml or env S2_API_KEY
  openalex_api_key: null    # OpenAlex API key -> config.local.yaml or env OPENALEX_API_KEY
  mineru_batch_size: 20     # cloud batch size per request (1-200, official limit)
  mineru_upload_workers: 4  # concurrent cloud conversion tasks (mineru-open-api compat layer)
  mineru_upload_retries: 3  # cloud upload retries per file, including the first attempt
  mineru_download_retries: 3 # cloud result download retries; legacy, kept for compatibility
  mineru_poll_timeout: 900  # single mineru-open-api conversion timeout (seconds)
  chunk_page_limit: 100     # auto-split PDFs exceeding this page count before conversion
  pdf_fallback_order: [auto] # fallback parser chain when MinerU is unavailable; auto = detect installed parsers
  pdf_fallback_auto_detect: true # auto-detect locally installed fallback parsers

search:
  top_k: 20

logging:
  level: INFO
  file: data/scrinium.log
  max_bytes: 10000000
  backup_count: 3
  metrics_db: data/metrics.db

zotero:
  library_type: user
"""

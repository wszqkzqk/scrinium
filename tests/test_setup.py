"""Tests for setup.py dependency probing, parser recommendation, and checks."""

from __future__ import annotations

import importlib
from pathlib import Path

import yaml

from scrinium.config import Config
from scrinium.setup import (
    _CONFIG_TEMPLATE,
    ParserChoice,
    _check_docling,
    _check_huggingface,
    _detect_mineru,
    _editable_project_root,
    _prompt_text,
    _wizard_deps,
    _wizard_keys,
    _wizard_parser,
    check_dep_group,
    recommend_pdf_parser,
    run_check,
)


def test_check_dep_group_treats_runtime_import_failure_as_missing(monkeypatch):
    original = importlib.import_module

    def fake_import(name: str, package=None):
        if name == "fitz":
            raise RuntimeError("pymupdf native failure")
        if package is None:
            return original(name)
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    status = check_dep_group("pdf")

    assert not status.installed
    assert "pymupdf" in status.missing


def test_check_dep_group_suppresses_import_side_effect_output(monkeypatch, capsys):
    original = importlib.import_module

    def fake_import(name: str, package=None):
        if name == "mermaid":
            print("noisy stdout during import")
            raise RuntimeError("optional backend warning")
        if package is None:
            return original(name)
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    status = check_dep_group("draw")

    captured = capsys.readouterr()
    assert not status.installed
    assert captured.out == ""
    assert captured.err == ""


def test_check_docling_uses_cli_presence(monkeypatch):
    monkeypatch.setattr("scrinium.setup.shutil.which", lambda name: "/usr/bin/docling" if name == "docling" else None)

    ok, detail = _check_docling("zh")

    assert ok is True
    assert detail == "/usr/bin/docling"


def test_check_docling_reports_actionable_install_guidance(monkeypatch):
    monkeypatch.setattr("scrinium.setup.shutil.which", lambda name: None)

    ok, detail = _check_docling("zh")

    assert ok is False
    assert "pip install docling" in detail
    assert "安装文档" in detail


def test_check_huggingface_uses_reachability_probe(monkeypatch):
    monkeypatch.setattr("scrinium.setup._probe_url", lambda url, timeout=2: url == "https://huggingface.co")

    ok, detail = _check_huggingface("zh")

    assert ok is True
    assert detail == "可达"


def test_check_huggingface_reports_actionable_failure(monkeypatch):
    monkeypatch.setattr("scrinium.setup._probe_url", lambda url, timeout=2: False)

    ok, detail = _check_huggingface("zh")

    assert ok is False
    assert "Docling" in detail
    assert "MinerU" in detail


def test_recommend_pdf_parser_prefers_mineru_when_both_reachable():
    parser_name, reason = recommend_pdf_parser(True, True, "zh")

    assert parser_name == "MinerU"
    assert "MinerU 可用" in reason
    assert "Hugging Face 也可达" in reason


def test_recommend_pdf_parser_prefers_docling_when_only_huggingface_reachable():
    parser_name, reason = recommend_pdf_parser(False, True, "zh")

    assert parser_name == "Docling"
    assert "Hugging Face 可达而 MinerU 不可用" in reason


def test_run_check_includes_parser_recommendation(monkeypatch):
    cfg = Config()
    monkeypatch.setattr("scrinium.setup._check_docling", lambda *_: (True, "docling ok"))
    monkeypatch.setattr("scrinium.setup._check_huggingface", lambda *_: (True, "hf ok"))
    monkeypatch.setattr("scrinium.setup.recommend_pdf_parser", lambda *args: ("MinerU", "both reachable"))

    results = run_check(cfg, "zh")

    labels = [item.label for item in results]
    assert "Docling" in labels
    assert "Hugging Face" in labels
    assert "PDF 解析器推荐" in labels


def test_run_check_includes_pdf_office_and_draw_dependency_groups(monkeypatch):
    cfg = Config()
    monkeypatch.setattr("scrinium.setup._check_docling", lambda *_: (True, "docling ok"))
    monkeypatch.setattr("scrinium.setup._check_huggingface", lambda *_: (True, "hf ok"))
    monkeypatch.setattr("scrinium.setup.recommend_pdf_parser", lambda *args: ("MinerU", "both reachable"))

    results = run_check(cfg, "zh")

    labels = [item.label for item in results]
    assert "PDF 依赖" in labels
    assert "Office 依赖" in labels
    assert "绘图依赖" in labels


def test_run_check_includes_optional_api_configuration_statuses(monkeypatch):
    cfg = Config()
    monkeypatch.setattr("scrinium.setup._check_docling", lambda *_: (True, "docling ok"))
    monkeypatch.setattr("scrinium.setup._check_huggingface", lambda *_: (True, "hf ok"))
    monkeypatch.setattr("scrinium.setup.recommend_pdf_parser", lambda *args: ("MinerU", "both reachable"))
    monkeypatch.setattr(cfg, "resolved_s2_api_key", lambda: "")
    monkeypatch.setattr(cfg, "resolved_zotero_api_key", lambda: "")

    results = run_check(cfg, "zh")

    result_map = {item.label: item for item in results}
    assert "Semantic Scholar API key" in result_map
    assert "Zotero API key" in result_map
    assert result_map["Semantic Scholar API key"].ok is True
    assert result_map["Zotero API key"].ok is True
    assert "可选" in result_map["Semantic Scholar API key"].detail
    assert "可选" in result_map["Zotero API key"].detail


def test_run_check_prefers_mineru_recommendation_when_cli_exists_without_token(monkeypatch):
    cfg = Config()
    monkeypatch.setattr(
        "scrinium.setup._detect_mineru",
        lambda *_args, **_kwargs: type(
            "MinerUStatus",
            (),
            {
                "ok": False,
                "detail": "cli present, token missing",
                "recommendable": True,
                "cloud_only": True,
                "cli_available": True,
                "token_configured": False,
            },
        )(),
    )
    monkeypatch.setattr("scrinium.setup._check_docling", lambda *_: (True, "docling ok"))
    monkeypatch.setattr("scrinium.setup._check_huggingface", lambda *_: (False, "hf down"))

    results = run_check(cfg, "zh")

    result_map = {item.label: item for item in results}
    assert result_map["PDF 解析器推荐"].detail.startswith("MinerU:")


def test_check_dep_group_supports_draw_extra(monkeypatch):
    original = importlib.import_module

    def fake_import(name: str, package=None):
        if name == "cli_anything":
            raise RuntimeError("bad optional import")
        if package is None:
            return original(name)
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    status = check_dep_group("draw")

    assert not status.installed
    assert "cli-anything-inkscape" in status.missing


def test_check_dep_group_treats_oserror_import_failure_as_missing(monkeypatch):
    original = importlib.import_module

    def fake_import(name: str, package=None):
        if name == "fitz":
            raise OSError("libstdc++.so missing")
        if package is None:
            return original(name)
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    status = check_dep_group("pdf")

    assert not status.installed
    assert "pymupdf" in status.missing


def test_detect_mineru_reports_actionable_failure(monkeypatch):
    cfg = Config()
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "")
    monkeypatch.setattr("scrinium.setup.shutil.which", lambda _name: None)

    class DummyRequests:
        @staticmethod
        def get(*_args, **_kwargs):
            raise RuntimeError("offline")

    monkeypatch.setitem(__import__("sys").modules, "requests", DummyRequests)

    status = _detect_mineru(cfg, "zh")

    assert status.ok is False
    assert "mineru-open-api" in status.detail
    assert "token" in status.detail
    assert "Docker" in status.detail


def test_detect_mineru_prefers_local_server_even_when_token_cli_missing(monkeypatch):
    cfg = Config()
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")
    monkeypatch.setattr("scrinium.setup.shutil.which", lambda _name: None)

    class DummyRequests:
        @staticmethod
        def get(*_args, **_kwargs):
            class _Resp:
                status_code = 200

            return _Resp()

    monkeypatch.setitem(__import__("sys").modules, "requests", DummyRequests)

    status = _detect_mineru(cfg, "en")

    assert status.ok is True
    assert "local server" in status.detail


def test_wizard_parser_mineru_choice_skips_auto_probe(monkeypatch, capsys):
    cfg = Config()
    answers = iter(["1", "y"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr("scrinium.setup._probe_url", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))

    choice = _wizard_parser(cfg, "zh")

    assert choice.parser == "mineru"
    assert choice.needs_mineru_key is False
    out = capsys.readouterr().out
    assert "已选择 MinerU" in out


def test_wizard_parser_auto_choice_shows_advisory_not_override(monkeypatch, capsys):
    cfg = Config()
    answers = iter(["3", "n"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr(
        "scrinium.setup.shutil.which", lambda name: "/usr/bin/mineru-open-api" if name == "mineru-open-api" else None
    )
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "")
    monkeypatch.setattr("scrinium.setup._probe_url", lambda url, timeout=2: "mineru.net" in url)

    choice = _wizard_parser(cfg, "zh")

    assert choice.parser == "mineru"
    assert choice.needs_mineru_key is True
    out = capsys.readouterr().out
    assert "检测到现有 MinerU token" not in out
    assert "尚未配置 MinerU API Token" in out
    assert "建议优先使用 MinerU" in out
    assert out.index("建议优先使用 MinerU") < out.index("如果你不打算本地部署")
    assert out.index("如果你不打算本地部署") < out.index("MinerU 本地部署指引")
    assert "如果你已经确定要用另一个" in out


def test_wizard_parser_auto_prefers_configured_mineru_before_probe(monkeypatch, capsys):
    cfg = Config()
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "mineru-key")
    answers = iter(["3", "n"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr(
        "scrinium.setup.shutil.which", lambda name: "/usr/bin/mineru-open-api" if name == "mineru-open-api" else None
    )
    monkeypatch.setattr("scrinium.setup._probe_url", lambda *_args, **_kwargs: False)

    choice = _wizard_parser(cfg, "zh")

    assert choice.parser == "mineru"
    assert choice.needs_mineru_key is True
    out = capsys.readouterr().out
    assert "建议优先使用 MinerU" in out
    assert out.index("建议优先使用 MinerU") < out.index("如果你不打算本地部署")


def test_wizard_parser_auto_detects_local_mineru_server(monkeypatch, capsys):
    cfg = Config()
    answers = iter(["3", "y"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr("scrinium.setup.shutil.which", lambda _name: None)
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "")
    monkeypatch.setattr("scrinium.setup._probe_url", lambda *_args, **_kwargs: False)

    class DummyRequests:
        @staticmethod
        def get(url, timeout=2):
            class _Resp:
                status_code = 200

            assert url == cfg.ingest.mineru_endpoint
            return _Resp()

    monkeypatch.setitem(__import__("sys").modules, "requests", DummyRequests)

    choice = _wizard_parser(cfg, "zh")

    assert choice.parser == "mineru"
    assert choice.needs_mineru_key is False
    out = capsys.readouterr().out
    assert "建议优先使用 MinerU" in out


def test_prompt_text_returns_empty_string_on_eof(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: (_ for _ in ()).throw(EOFError()))

    value = _prompt_text("  > ")

    assert value == ""


def test_wizard_deps_does_not_auto_install_when_input_stream_hits_eof(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: (_ for _ in ()).throw(EOFError()))
    monkeypatch.setattr(
        "scrinium.setup.check_dep_group",
        lambda group: type("Status", (), {"installed": group != "pdf", "missing": ["pymupdf"]})(),
    )

    called = []

    def fake_run(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("pip install should not run on EOF")

    monkeypatch.setattr("scrinium.setup.subprocess.run", fake_run)

    _wizard_deps("zh")

    out = capsys.readouterr().out
    assert called == []
    assert "已跳过" in out


def test_wizard_parser_auto_prefers_mineru_when_cli_exists_even_without_token_probe(monkeypatch, capsys):
    cfg = Config()
    answers = iter(["3", "n"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr(
        "scrinium.setup.shutil.which", lambda name: "/usr/bin/mineru-open-api" if name == "mineru-open-api" else None
    )
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "")
    monkeypatch.setattr("scrinium.setup._probe_url", lambda *_args, **_kwargs: False)

    choice = _wizard_parser(cfg, "zh")

    assert choice.parser == "mineru"
    assert choice.needs_mineru_key is True
    out = capsys.readouterr().out
    assert "建议优先使用 MinerU" in out
    assert "免费" in out
    assert "Token" in out or "token" in out


def test_wizard_parser_auto_choice_defaults_to_cloud_key_on_eof(monkeypatch):
    cfg = Config()
    answers = iter(["3", ""])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr(
        "scrinium.setup.shutil.which", lambda name: "/usr/bin/mineru-open-api" if name == "mineru-open-api" else None
    )
    monkeypatch.setattr("scrinium.setup._probe_url", lambda url, timeout=2: "mineru.net" in url)

    choice = _wizard_parser(cfg, "zh")

    assert choice.parser == "mineru"
    assert choice.needs_mineru_key is True


def test_wizard_keys_persists_docling_parser_preference(tmp_path, monkeypatch):
    answers = iter(["", ""])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))

    _wizard_keys(tmp_path, "zh", ParserChoice(parser="docling", needs_mineru_key=False))

    local_cfg = (tmp_path / "config.local.yaml").read_text(encoding="utf-8")
    assert "pdf_preferred_parser: docling" in local_cfg


def test_wizard_keys_handles_null_ingest_section(tmp_path, monkeypatch):
    (tmp_path / "config.local.yaml").write_text("ingest: null\n", encoding="utf-8")
    answers = iter(["", ""])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))

    _wizard_keys(tmp_path, "zh", ParserChoice(parser="docling", needs_mineru_key=False))

    local_cfg = (tmp_path / "config.local.yaml").read_text(encoding="utf-8")
    assert "pdf_preferred_parser: docling" in local_cfg


def test_wizard_keys_handles_non_mapping_local_config(tmp_path, monkeypatch):
    (tmp_path / "config.local.yaml").write_text("- unexpected\n", encoding="utf-8")
    answers = iter(["", ""])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))

    _wizard_keys(tmp_path, "zh", ParserChoice(parser="docling", needs_mineru_key=False))

    local_cfg = (tmp_path / "config.local.yaml").read_text(encoding="utf-8")
    assert "pdf_preferred_parser: docling" in local_cfg


def test_wizard_keys_skips_creating_local_config_when_default_parser_and_no_new_values(tmp_path, monkeypatch, capsys):
    answers = iter(["", "", ""])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))

    _wizard_keys(tmp_path, "zh", ParserChoice(parser="mineru", needs_mineru_key=True))

    out = capsys.readouterr().out
    assert not (tmp_path / "config.local.yaml").exists()
    assert "未配置任何密钥" in out


def test_wizard_keys_cleans_redundant_default_parser_override(tmp_path, monkeypatch, capsys):
    (tmp_path / "config.local.yaml").write_text(
        "ingest:\n  mineru_api_key: existing-mineru-key\n  pdf_preferred_parser: mineru\n",
        encoding="utf-8",
    )
    answers = iter(["", "", ""])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))

    _wizard_keys(tmp_path, "zh", ParserChoice(parser="mineru", needs_mineru_key=True))

    out = capsys.readouterr().out
    assert "已保存到 config.local.yaml" in out
    local_cfg = (tmp_path / "config.local.yaml").read_text(encoding="utf-8")
    assert "pdf_preferred_parser" not in local_cfg
    assert "existing-mineru-key" in local_cfg


def test_config_template_stays_in_sync_with_config_yaml():
    """The setup wizard template must not drift behind the shipped config.yaml."""
    template = yaml.safe_load(_CONFIG_TEMPLATE)
    repo_root = Path(__file__).resolve().parent.parent
    shipped = yaml.safe_load((repo_root / "config.yaml").read_text(encoding="utf-8"))

    assert set(shipped) <= set(template), f"template missing sections: {set(shipped) - set(template)}"
    for section in ("paths", "ingest", "search", "logging", "zotero"):
        missing = set(shipped[section]) - set(template[section])
        assert not missing, f"template {section} section missing keys: {missing}"
    # Removed sections must not reappear in either file.
    for removed in ("llm", "translate", "embed", "topics"):
        assert removed not in template, f"template still has removed section: {removed}"
        assert removed not in shipped, f"config.yaml still has removed section: {removed}"


class _FakeDist:
    """Minimal importlib.metadata Distribution stand-in for editable probing."""

    def __init__(self, name, direct_url=None):
        self.metadata = {"Name": name}
        self._direct_url = direct_url

    def read_text(self, filename):
        if filename == "direct_url.json":
            return self._direct_url
        return None


def test_editable_project_root_detects_editable_install(monkeypatch):
    dists = [
        _FakeDist("scrinium"),  # stale egg-info without direct_url.json
        _FakeDist("requests"),
        _FakeDist("scrinium", '{"url": "file:///src/scrinium", "dir_info": {"editable": true}}'),
    ]
    monkeypatch.setattr("scrinium.setup.importlib.metadata.distributions", lambda: dists)

    root = _editable_project_root()

    assert root is not None
    assert (root / "pyproject.toml").exists()


def test_editable_project_root_returns_none_for_regular_install(monkeypatch):
    dists = [
        _FakeDist("scrinium", '{"url": "https://pypi.org", "dir_info": {}}'),
    ]
    monkeypatch.setattr("scrinium.setup.importlib.metadata.distributions", lambda: dists)

    assert _editable_project_root() is None


def test_wizard_deps_uses_editable_install_for_local_checkout(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'scrinium'\n", encoding="utf-8")
    monkeypatch.setattr("scrinium.setup._editable_project_root", lambda: tmp_path)
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: "y")
    monkeypatch.setattr(
        "scrinium.setup.check_dep_group",
        lambda group: type("Status", (), {"installed": group != "pdf", "missing": ["pymupdf"]})(),
    )

    calls = []

    class _Result:
        returncode = 0
        stderr = ""

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return _Result()

    monkeypatch.setattr("scrinium.setup.subprocess.run", fake_run)

    _wizard_deps("zh")

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert "-e" in args
    assert ".[pdf]" in args
    assert kwargs["cwd"] == tmp_path
    out = capsys.readouterr().out
    assert 'pip install -e ".[pdf]"' in out


def test_wizard_deps_uses_pypi_name_for_regular_install(monkeypatch, capsys):
    monkeypatch.setattr("scrinium.setup._editable_project_root", lambda: None)
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: "y")
    monkeypatch.setattr(
        "scrinium.setup.check_dep_group",
        lambda group: type("Status", (), {"installed": group != "pdf", "missing": ["pymupdf"]})(),
    )

    calls = []

    class _Result:
        returncode = 0
        stderr = ""

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return _Result()

    monkeypatch.setattr("scrinium.setup.subprocess.run", fake_run)

    _wizard_deps("zh")

    assert len(calls) == 1
    args, _ = calls[0]
    assert "scrinium[pdf]" in args
    assert "-e" not in args
    out = capsys.readouterr().out
    assert "pip install scrinium[pdf]" in out

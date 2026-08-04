"""Tests for scrinium.config — YAML loading, merging, path resolution, defaults."""

from __future__ import annotations

import logging

import pytest

import scrinium.config as config_mod
from scrinium.config import _build_config, _deep_merge, _find_config_file, load_config


class TestDeepMerge:
    def test_scalar_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        assert _deep_merge(base, override) == {"a": 1, "b": 99}

    def test_nested_merge(self):
        base = {"search": {"top_k": 20, "timeout": 30}}
        override = {"search": {"timeout": 60}}
        result = _deep_merge(base, override)
        assert result == {"search": {"top_k": 20, "timeout": 60}}

    def test_add_new_keys(self):
        base = {"a": 1}
        override = {"b": 2}
        assert _deep_merge(base, override) == {"a": 1, "b": 2}

    def test_empty_override(self):
        base = {"a": 1}
        assert _deep_merge(base, {}) == {"a": 1}

    def test_empty_base(self):
        override = {"a": 1}
        assert _deep_merge({}, override) == {"a": 1}

    def test_override_dict_with_scalar(self):
        base = {"a": {"nested": True}}
        override = {"a": "flat"}
        assert _deep_merge(base, override) == {"a": "flat"}

    def test_deep_nesting(self):
        base = {"a": {"b": {"c": 1, "d": 2}}}
        override = {"a": {"b": {"c": 99}}}
        result = _deep_merge(base, override)
        assert result == {"a": {"b": {"c": 99, "d": 2}}}


class TestBuildConfig:
    def test_empty_dict_uses_defaults(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.paths.papers_dir == "data/papers"
        assert cfg.search.top_k == 20

    def test_partial_override(self, tmp_path):
        data = {"search": {"top_k": 42}}
        cfg = _build_config(data, tmp_path)
        assert cfg.search.top_k == 42
        assert cfg.paths.papers_dir == "data/papers"  # default preserved

    def test_ingest_defaults(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.ingest.chunk_page_limit == 100
        assert cfg.ingest.mineru_batch_size == 20
        assert cfg.ingest.mineru_upload_workers == 4
        assert cfg.ingest.mineru_upload_retries == 3
        assert cfg.ingest.mineru_download_retries == 3
        assert cfg.ingest.mineru_poll_timeout == 900
        assert cfg.ingest.pdf_preferred_parser == "mineru"
        assert cfg.ingest.pdf_fallback_order == ["auto"]
        assert cfg.ingest.pdf_fallback_auto_detect is True

    def test_ingest_fallback_order_override(self, tmp_path):
        cfg = _build_config(
            {
                "ingest": {
                    "pdf_preferred_parser": "docling",
                    "pdf_fallback_order": ["pymupdf"],
                    "pdf_fallback_auto_detect": False,
                }
            },
            tmp_path,
        )
        assert cfg.ingest.pdf_preferred_parser == "docling"
        assert cfg.ingest.pdf_fallback_order == ["pymupdf"]
        assert cfg.ingest.pdf_fallback_auto_detect is False

    def test_ingest_fallback_order_accepts_single_string(self, tmp_path):
        cfg = _build_config({"ingest": {"pdf_fallback_order": "auto"}}, tmp_path)
        assert cfg.ingest.pdf_fallback_order == ["auto"]

    def test_ingest_choice_fields_are_case_insensitive(self, tmp_path):
        cfg = _build_config(
            {
                "ingest": {
                    "mineru_backend_local": "Pipeline",
                    "mineru_parse_method": "OCR",
                    "pdf_preferred_parser": "Docling",
                }
            },
            tmp_path,
        )
        assert cfg.ingest.mineru_backend_local == "pipeline"
        assert cfg.ingest.mineru_parse_method == "ocr"
        assert cfg.ingest.pdf_preferred_parser == "docling"

    def test_ingest_fallback_order_ignores_null_and_non_string_entries(self, tmp_path):
        cfg = _build_config({"ingest": {"pdf_fallback_order": ["auto", None, 123, "docling"]}}, tmp_path)
        assert cfg.ingest.pdf_fallback_order == ["auto", "docling"]

    def test_ingest_fallback_order_invalid_scalar_type_warns_and_uses_default(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            cfg = _build_config({"ingest": {"pdf_fallback_order": 123}}, tmp_path)

        assert cfg.ingest.pdf_fallback_order == ["auto"]
        assert "invalid string-list config value" in caplog.text

    def test_ingest_fallback_auto_detect_parses_string_bool(self, tmp_path):
        cfg = _build_config({"ingest": {"pdf_fallback_auto_detect": "false"}}, tmp_path)
        assert cfg.ingest.pdf_fallback_auto_detect is False

    def test_ingest_fallback_auto_detect_none_uses_default(self, tmp_path):
        cfg = _build_config({"ingest": {"pdf_fallback_auto_detect": None}}, tmp_path)
        assert cfg.ingest.pdf_fallback_auto_detect is True

    def test_null_sections_handled(self, tmp_path):
        data = {"paths": None, "search": None}
        cfg = _build_config(data, tmp_path)
        assert cfg.paths.papers_dir == "data/papers"
        assert cfg.search.top_k == 20

    def test_zotero_library_id_coerced_to_str(self, tmp_path):
        data = {"zotero": {"library_id": 12345}}
        cfg = _build_config(data, tmp_path)
        assert cfg.zotero.library_id == "12345"

    def test_zotero_library_type_default_and_override(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.zotero.library_type == "user"

        cfg2 = _build_config({"zotero": {"library_type": "group"}}, tmp_path)
        assert cfg2.zotero.library_type == "group"

    def test_mineru_formula_and_table_null_use_defaults(self, tmp_path):
        data = {
            "ingest": {
                "mineru_enable_formula": None,
                "mineru_enable_table": None,
            }
        }
        cfg = _build_config(data, tmp_path)
        assert cfg.ingest.mineru_enable_formula is True
        assert cfg.ingest.mineru_enable_table is True

    def test_invalid_mineru_pdf_cloud_settings_fall_back_to_safe_defaults(self, tmp_path):
        data = {
            "ingest": {
                "mineru_backend_local": "unknown-backend",
                "mineru_model_version_cloud": "MinerU-HTML",
                "mineru_lang": "",
                "mineru_parse_method": "bad-mode",
                "mineru_batch_size": 999,
                "pdf_preferred_parser": "bad-parser",
            }
        }
        cfg = _build_config(data, tmp_path)
        assert cfg.ingest.mineru_backend_local == "pipeline"
        assert cfg.ingest.mineru_model_version_cloud == "pipeline"
        assert cfg.ingest.mineru_lang == "ch"
        assert cfg.ingest.mineru_parse_method == "auto"
        assert cfg.ingest.mineru_batch_size == 200
        assert cfg.ingest.pdf_preferred_parser == "mineru"

    def test_mineru_lang_is_normalized_to_lowercase(self, tmp_path):
        cfg = _build_config({"ingest": {"mineru_lang": " EN "}}, tmp_path)
        assert cfg.ingest.mineru_lang == "en"

    def test_mineru_cloud_model_version_is_case_insensitive(self, tmp_path):
        cfg = _build_config({"ingest": {"mineru_model_version_cloud": " VLM "}}, tmp_path)
        assert cfg.ingest.mineru_model_version_cloud == "vlm"

    def test_zero_or_negative_mineru_batch_size_uses_default(self, tmp_path):
        cfg = _build_config({"ingest": {"mineru_batch_size": 0}}, tmp_path)
        assert cfg.ingest.mineru_batch_size == 20


class TestDeprecatedSections:
    """Removed llm/translate/embed/topics sections warn once and are ignored."""

    @pytest.fixture(autouse=True)
    def _reset_warned(self):
        config_mod._warned_deprecated.clear()
        yield
        config_mod._warned_deprecated.clear()

    def test_llm_section_warns_and_is_ignored(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="scrinium.config"):
            cfg = _build_config({"llm": {"model": "gpt-4"}}, tmp_path)
        assert "config section 'llm' is deprecated and ignored" in caplog.text
        assert not hasattr(cfg, "llm")

    def test_all_four_sections_warn(self, tmp_path, caplog):
        data = {"llm": {}, "translate": {}, "embed": {}, "topics": {}}
        with caplog.at_level(logging.WARNING, logger="scrinium.config"):
            _build_config(data, tmp_path)
        for section in ("llm", "translate", "embed", "topics"):
            assert f"config section {section!r} is deprecated and ignored" in caplog.text

    def test_warning_is_one_time(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="scrinium.config"):
            _build_config({"llm": {}}, tmp_path)
            _build_config({"llm": {}}, tmp_path)
        assert caplog.text.count("config section 'llm' is deprecated") == 1

    def test_non_regex_extractor_warns_and_is_ignored(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="scrinium.config"):
            cfg = _build_config({"ingest": {"extractor": "robust"}}, tmp_path)
        assert "config ingest.extractor='robust' is deprecated and ignored" in caplog.text
        assert not hasattr(cfg.ingest, "extractor")

    def test_regex_extractor_does_not_warn(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="scrinium.config"):
            _build_config({"ingest": {"extractor": "regex"}}, tmp_path)
        assert "ingest.extractor" not in caplog.text

    def test_no_warning_without_deprecated_keys(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="scrinium.config"):
            _build_config({"search": {"top_k": 5}}, tmp_path)
        assert "deprecated" not in caplog.text


class TestConfigProperties:
    def test_papers_dir_absolute(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.papers_dir.is_absolute()
        assert cfg.papers_dir == (tmp_path / "data" / "papers").resolve()

    def test_index_db_absolute(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.index_db.is_absolute()
        assert cfg.index_db == (tmp_path / "data" / "index.db").resolve()

    def test_log_file_absolute(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.log_file.is_absolute()

    def test_metrics_db_path(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.metrics_db_path == (tmp_path / "data" / "metrics.db").resolve()


class TestEnsureDirs:
    def test_creates_required_dirs(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        assert cfg.papers_dir.exists()
        assert (tmp_path / "data" / "inbox").exists()
        assert (tmp_path / "data" / "inbox-proceedings").exists()
        assert (tmp_path / "data" / "inbox-thesis").exists()
        assert (tmp_path / "data" / "inbox-doc").exists()
        assert (tmp_path / "data" / "pending").exists()
        assert (tmp_path / "data" / "proceedings").exists()
        assert (tmp_path / "workspace").exists()

    def test_idempotent(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        cfg.ensure_dirs()  # should not raise


class TestResolvedApiKey:
    def test_mineru_key_from_config(self, tmp_path):
        cfg = _build_config({"ingest": {"mineru_api_key": "mu-key"}}, tmp_path)
        assert cfg.resolved_mineru_api_key() == "mu-key"

    def test_mineru_key_from_env(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        monkeypatch.setenv("MINERU_API_KEY", "mu-env")
        assert cfg.resolved_mineru_api_key() == "mu-env"

    def test_mineru_token_env_wins_over_legacy_api_key_env(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        monkeypatch.setenv("MINERU_TOKEN", "new-token")
        monkeypatch.setenv("MINERU_API_KEY", "legacy-token")
        assert cfg.resolved_mineru_api_key() == "new-token"

    def test_s2_key_from_config(self, tmp_path):
        cfg = _build_config({"ingest": {"s2_api_key": "s2-cfg"}}, tmp_path)
        assert cfg.resolved_s2_api_key() == "s2-cfg"

    def test_s2_key_from_env(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        monkeypatch.setenv("S2_API_KEY", "s2-env")
        assert cfg.resolved_s2_api_key() == "s2-env"

    def test_s2_key_config_wins_over_env(self, tmp_path, monkeypatch):
        cfg = _build_config({"ingest": {"s2_api_key": "s2-cfg"}}, tmp_path)
        monkeypatch.setenv("S2_API_KEY", "s2-env")
        assert cfg.resolved_s2_api_key() == "s2-cfg"

    def test_s2_key_empty_when_unset(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        monkeypatch.delenv("S2_API_KEY", raising=False)
        assert cfg.resolved_s2_api_key() == ""


class TestLoadConfig:
    def test_load_from_explicit_path(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("search:\n  top_k: 42\n", encoding="utf-8")
        cfg = load_config(cfg_file)
        assert cfg.search.top_k == 42

    def test_local_yaml_overrides(self, tmp_path):
        (tmp_path / "config.yaml").write_text(
            "search:\n  top_k: 30\n",
            encoding="utf-8",
        )
        (tmp_path / "config.local.yaml").write_text(
            "search:\n  top_k: 41\n",
            encoding="utf-8",
        )
        cfg = load_config(tmp_path / "config.yaml")
        assert cfg.search.top_k == 41

    def test_nonexistent_path_uses_defaults(self, tmp_path):
        cfg = load_config(tmp_path / "nonexistent.yaml")
        assert cfg.search.top_k == 20

    def test_empty_yaml(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("", encoding="utf-8")
        cfg = load_config(cfg_file)
        assert cfg.search.top_k == 20

    def test_env_var_config_path(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "custom.yaml"
        cfg_file.write_text("search:\n  top_k: 42\n", encoding="utf-8")
        monkeypatch.setenv("SCRINIUM_CONFIG", str(cfg_file))
        cfg = load_config()
        assert cfg.search.top_k == 42


class TestLegacyEnvFallback:
    """Deprecated SCHOLARAIO_* env vars still work after the fork rename."""

    def test_legacy_config_env_var_fallback(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "custom.yaml"
        cfg_file.write_text("search:\n  top_k: 43\n", encoding="utf-8")
        monkeypatch.delenv("SCRINIUM_CONFIG", raising=False)
        monkeypatch.setenv("SCHOLARAIO_CONFIG", str(cfg_file))
        cfg = load_config()
        assert cfg.search.top_k == 43

    def test_legacy_global_config_dir_fallback(self, tmp_path, monkeypatch, caplog):
        from pathlib import Path

        home = tmp_path / "home"
        legacy_cfg = home / ".scholaraio" / "config.yaml"
        legacy_cfg.parent.mkdir(parents=True)
        legacy_cfg.write_text("search:\n  top_k: 44\n", encoding="utf-8")
        deep_cwd = tmp_path / "a" / "b" / "c" / "d" / "e" / "f" / "g"
        deep_cwd.mkdir(parents=True)
        monkeypatch.chdir(deep_cwd)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        monkeypatch.delenv("SCRINIUM_CONFIG", raising=False)
        monkeypatch.delenv("SCHOLARAIO_CONFIG", raising=False)
        with caplog.at_level(logging.WARNING):
            found = _find_config_file()
        assert found == legacy_cfg
        assert "legacy global config" in caplog.text

    def test_new_global_config_dir_wins_over_legacy(self, tmp_path, monkeypatch):
        from pathlib import Path

        home = tmp_path / "home"
        new_cfg = home / ".scrinium" / "config.yaml"
        new_cfg.parent.mkdir(parents=True)
        new_cfg.write_text("", encoding="utf-8")
        legacy_cfg = home / ".scholaraio" / "config.yaml"
        legacy_cfg.parent.mkdir(parents=True)
        legacy_cfg.write_text("", encoding="utf-8")
        deep_cwd = tmp_path / "a" / "b" / "c" / "d" / "e" / "f" / "g"
        deep_cwd.mkdir(parents=True)
        monkeypatch.chdir(deep_cwd)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        assert _find_config_file() == new_cfg

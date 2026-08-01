"""Tests for scholaraio.prompts — registry integrity and the parse_llm_json contract.

Golden tests only: no LLM calls. Prompt rendering compatibility with the
pre-refactor inline strings is verified separately (byte-identical renders);
these tests lock the parsing contract and registry shape going forward.
"""

from __future__ import annotations

import pytest

from scholaraio.prompts import (
    DETECT_TYPE_PARAMS,
    PROMPTS,
    Prompt,
    build_doc_extract_prompt,
    parse_llm_json,
    render_detect_prompt,
)

EXPECTED_NAMES = {
    "extract.llm",
    "extract.robust",
    "detect_thesis",
    "detect_book",
    "doc_extract",
    "abstract.extract",
    "abstract.verify",
    "loader.toc",
    "loader.l3_primary",
    "loader.l3_fallback",
    "loader.l3_validate",
    "translate",
}


class TestParseLlmJson:
    def test_plain_object(self):
        assert parse_llm_json('{"a": 1, "b": [2, 3]}') == {"a": 1, "b": [2, 3]}

    def test_fenced_json_block(self):
        text = 'Sure, here you go:\n```json\n{"a": 1}\n```\nHope this helps.'
        assert parse_llm_json(text) == {"a": 1}

    def test_fenced_block_without_lang_tag(self):
        assert parse_llm_json('```\n{"a": 1}\n```') == {"a": 1}

    def test_bare_object_embedded_in_prose(self):
        assert parse_llm_json('The answer is {"is_thesis": true} — done.') == {"is_thesis": True}

    def test_nested_braces_greedy(self):
        assert parse_llm_json('{"toc": [{"line": 3}]}') == {"toc": [{"line": 3}]}

    def test_latex_backslashes_repaired(self):
        # Invalid JSON escapes (\a, \v) get a backslash fix-up pass
        result = parse_llm_json(r'{"conclusion": "see \alpha and \vec{x}"}')
        assert result == {"conclusion": r"see \alpha and \vec{x}"}

    def test_valid_escapes_preserved(self):
        # \n is a valid JSON escape and must stay a newline
        assert parse_llm_json(r'{"a": "line\nbreak"}') == {"a": "line\nbreak"}

    def test_truncated_json_returns_none(self):
        assert parse_llm_json('{"a": 1') is None

    def test_truncated_fenced_json_returns_none(self):
        assert parse_llm_json('```json\n{"a": 1\n```') is None

    def test_empty_response_returns_none(self):
        assert parse_llm_json("") is None
        assert parse_llm_json("   \n  ") is None

    def test_non_object_json_returns_none(self):
        assert parse_llm_json("[1, 2, 3]") is None
        assert parse_llm_json('"just a string"') is None

    def test_garbage_returns_none(self):
        assert parse_llm_json("no json here at all") is None


class TestRegistry:
    def test_expected_prompt_names(self):
        assert set(PROMPTS) == EXPECTED_NAMES

    def test_entries_are_prompt_dataclass_with_matching_name(self):
        for key, prompt in PROMPTS.items():
            assert isinstance(prompt, Prompt)
            assert prompt.name == key
            assert prompt.template

    def test_json_mode_flags(self):
        free_text = {"abstract.extract", "abstract.verify", "translate"}
        for name, prompt in PROMPTS.items():
            assert prompt.json_mode is (name not in free_text)

    def test_extractor_prompts_share_schema_and_rules_tail(self):
        # The two extractor prompts are composed as shared base + per-mode
        # increment; the shared segments must appear verbatim in both.
        shared_schema = '"authors": ["姓名1", "姓名2", ...],'
        shared_rules = "- authors 找不到时填空列表 []\n- year 必须是整数或 null\n- 只返回 JSON，不要任何解释文字"
        for name in ("extract.llm", "extract.robust"):
            assert shared_schema in PROMPTS[name].template
            assert shared_rules in PROMPTS[name].template


class TestDetectParams:
    def test_covers_thesis_and_book(self):
        assert set(DETECT_TYPE_PARAMS) == {"thesis", "book"}

    def test_params_shape(self):
        for kind, params in DETECT_TYPE_PARAMS.items():
            assert params["json_key"] == f"is_{kind}"
            assert params["kind_desc"]
            assert params["indicators"]

    def test_render_has_boolean_key_first(self):
        # max_tokens is only 200, so the boolean verdict must precede reason
        for kind in ("thesis", "book"):
            prompt = render_detect_prompt(kind, "DOC EXCERPT")
            needle = f'{{"{DETECT_TYPE_PARAMS[kind]["json_key"]}": true/false, "reason"'
            assert needle in prompt
            assert prompt.index('"is_') < prompt.index('"reason"')
            assert "DOC EXCERPT" in prompt

    def test_unknown_kind_raises(self):
        with pytest.raises(KeyError):
            render_detect_prompt("patent", "text")


class TestDocExtractPrompt:
    def test_no_fencing_requested(self):
        # The old prompt demanded a ```json fence, contradicting json_mode
        prompt = build_doc_extract_prompt("DOC", has_title=False, has_abstract=False)
        assert "Return JSON only, no fencing" in prompt
        assert "```" not in prompt

    def test_existing_title_included(self):
        prompt = build_doc_extract_prompt("DOC", has_title=True, has_abstract=False, existing_title="My Title")
        assert "Existing title: My Title" in prompt
        assert "summary" in prompt


class TestCallSiteDelegates:
    """Thin compatibility wrappers delegate to parse_llm_json."""

    def test_pipeline_parse_detect_json(self):
        from scholaraio.ingest.pipeline import _parse_detect_json

        assert _parse_detect_json('```json\n{"is_book": true}\n```') == {"is_book": True}
        assert _parse_detect_json("garbage") == {}

    def test_doc_extract_parse_llm_response(self):
        from scholaraio.ingest.metadata._doc_extract import _parse_llm_response

        assert _parse_llm_response('prefix {"title": "T"} suffix') == {"title": "T"}
        assert _parse_llm_response("garbage") == {}

    def test_loader_parse_json_raises_on_failure(self):
        from scholaraio.loader import _parse_json

        assert _parse_json('{"line": 3}') == {"line": 3}
        with pytest.raises(ValueError):
            _parse_json("not json")

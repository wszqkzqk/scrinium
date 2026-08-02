"""Tests for translate.py — language detection, chunk splitting, and prompt building.

Covers pure-function logic that doesn't require LLM calls.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from scrinium.translate import (
    SKIP_ALL_CHUNKS_FAILED,
    _build_translate_prompt,
    _split_into_chunks,
    _translate_chunk_with_retry,
    _translation_workdir,
    batch_translate,
    detect_language,
    translate_paper,
    validate_lang,
)


class TestDetectLanguage:
    """Language detection heuristics."""

    def test_english_text(self):
        assert detect_language("This is an English sentence about turbulence modeling.") == "en"

    def test_chinese_text(self):
        assert detect_language("本文提出了一种新型湍流模型，用于边界层流动的数值模拟。") == "zh"

    def test_japanese_mixed_kanji_kana(self):
        assert detect_language("この論文では境界層の乱流モデルについて述べる。") == "ja"

    def test_japanese_kana_only(self):
        """Kana-dominant text (few/no kanji) should still be detected as Japanese."""
        assert detect_language("これはテストです。すべてひらがなとカタカナで書かれています。") == "ja"

    def test_korean_text(self):
        assert detect_language("이 논문은 경계층 난류 모델에 대해 설명합니다.") == "ko"

    def test_german_text(self):
        text = "Dies ist eine wissenschaftliche Arbeit und die Ergebnisse sind in der Studie beschrieben."
        assert detect_language(text) == "de"

    def test_french_text(self):
        text = "Cette etude presente une analyse de la couche limite et des resultats experimentaux."
        assert detect_language(text) == "fr"

    def test_spanish_text(self):
        text = "Este articulo presenta una revision de la literatura y de los resultados para el modelo."
        assert detect_language(text) == "es"

    def test_empty_text_defaults_to_english(self):
        assert detect_language("") == "en"

    def test_math_only_defaults_to_english(self):
        assert detect_language("$$E = mc^2$$  $\\alpha + \\beta$") == "en"

    def test_code_blocks_stripped(self):
        """Code blocks should not influence language detection."""
        text = "这是中文文本。\n```python\nprint('hello world')\n```\n继续中文。"
        assert detect_language(text) == "zh"


class TestValidateLang:
    """Language code validation and normalization."""

    def test_normalizes_case_and_whitespace(self):
        assert validate_lang(" ZH ") == "zh"

    def test_rejects_non_string_inputs(self):
        with pytest.raises(ValueError, match="type"):
            validate_lang(None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="type"):
            validate_lang(123)  # type: ignore[arg-type]

    def test_rejects_invalid_pattern(self):
        with pytest.raises(ValueError, match="expected 2-5 lowercase letters"):
            validate_lang("zh-cn")


class TestSplitIntoChunks:
    """Chunk splitting with placeholder protection."""

    def test_small_text_single_chunk(self):
        text = "Hello world.\n\nSecond paragraph."
        chunks = _split_into_chunks(text, chunk_size=1000)
        assert len(chunks) == 1
        assert "Hello world." in chunks[0]
        assert "Second paragraph." in chunks[0]

    def test_respects_chunk_size(self):
        text = "A" * 100 + "\n\n" + "B" * 100
        chunks = _split_into_chunks(text, chunk_size=120)
        assert len(chunks) == 2

    def test_code_block_preserved_intact(self):
        code = "```python\nfor i in range(10):\n    print(i)\n```"
        text = f"Before code.\n\n{code}\n\nAfter code."
        chunks = _split_into_chunks(text, chunk_size=5000)
        full = "\n\n".join(chunks)
        assert code in full

    def test_display_math_preserved_intact(self):
        math = "$$\\int_0^\\infty e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}$$"
        text = f"Some text.\n\n{math}\n\nMore text."
        chunks = _split_into_chunks(text, chunk_size=5000)
        full = "\n\n".join(chunks)
        assert math in full

    def test_inline_math_preserved_intact(self):
        text = "The result is $\\alpha + \\beta = \\gamma$ which is important."
        chunks = _split_into_chunks(text, chunk_size=5000)
        full = "\n\n".join(chunks)
        assert "$\\alpha + \\beta = \\gamma$" in full

    def test_inline_math_not_split_across_chunks(self):
        """Inline math should not be broken when hard-splitting oversized text."""
        formula = "$E = mc^2$"
        big_text = "Word. " * 80 + formula + " " + "Word. " * 80
        chunks = _split_into_chunks(big_text, chunk_size=200)
        # The formula should appear complete in exactly one chunk
        found = [c for c in chunks if formula in c]
        assert len(found) == 1

    def test_image_preserved_intact(self):
        img = "![Figure 1](images/fig1.png)"
        text = f"Caption above.\n\n{img}\n\nCaption below."
        chunks = _split_into_chunks(text, chunk_size=5000)
        full = "\n\n".join(chunks)
        assert img in full

    def test_protected_blocks_not_split_across_chunks(self):
        """A code block should stay in one chunk even when splitting."""
        code = "```\n" + "x\n" * 50 + "```"
        text = "Intro.\n\n" + code + "\n\nEnd."
        chunks = _split_into_chunks(text, chunk_size=80)
        # The code block should appear completely in exactly one chunk
        found = [c for c in chunks if "```" in c]
        assert len(found) >= 1
        for c in found:
            assert c.count("```") % 2 == 0, "Code fence should not be split"

    def test_oversized_paragraph_gets_secondary_split(self):
        """A single paragraph larger than chunk_size is further split."""
        big_para = "Word. " * 500  # ~3000 chars, no double-newlines
        chunks = _split_into_chunks(big_para, chunk_size=500)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c) <= 600  # allow some margin

    def test_order_preserved(self):
        paragraphs = [f"Paragraph {i}." for i in range(5)]
        text = "\n\n".join(paragraphs)
        chunks = _split_into_chunks(text, chunk_size=30)
        rejoined = "\n\n".join(chunks)
        for p in paragraphs:
            assert p in rejoined


class TestBuildTranslatePrompt:
    """Prompt construction with terminology rules."""

    def test_chinese_includes_terminology_rule(self):
        prompt = _build_translate_prompt("Hello", "zh", "中文")
        assert "「英文 (中文翻译)」" in prompt

    def test_japanese_includes_terminology_rule(self):
        prompt = _build_translate_prompt("Hello", "ja", "日本語")
        assert "英語 (日本語訳)" in prompt

    def test_english_has_no_terminology_rule(self):
        prompt = _build_translate_prompt("Hello", "en", "English")
        # Should not contain any CJK terminology format
        assert "「" not in prompt

    def test_prompt_contains_source_text(self):
        prompt = _build_translate_prompt("Test input text", "zh", "中文")
        assert "Test input text" in prompt

    def test_prompt_contains_target_language(self):
        prompt = _build_translate_prompt("text", "de", "Deutsch")
        assert "Deutsch" in prompt


class TestTranslatePaper:
    def test_translate_paper_translates_chunks_concurrently_and_writes_in_order(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "Smith-2023-Test"
        paper_dir.mkdir(parents=True)
        (paper_dir / "paper.md").write_text("Original text", encoding="utf-8")
        (paper_dir / "meta.json").write_text("{}", encoding="utf-8")

        cfg = SimpleNamespace(
            translate=SimpleNamespace(target_lang="zh", chunk_size=1000, concurrency=3),
            llm=SimpleNamespace(model="test-model"),
        )

        monkeypatch.setattr("scrinium.translate.detect_language", lambda text: "en")
        monkeypatch.setattr(
            "scrinium.translate._split_into_chunks", lambda text, chunk_size: ["chunk-1", "chunk-2", "chunk-3"]
        )

        state = {"in_flight": 0, "max_in_flight": 0}
        lock = threading.Lock()
        delays = {"chunk-1": 0.15, "chunk-2": 0.05, "chunk-3": 0.1}
        outputs = {"chunk-1": "译文-1", "chunk-2": "译文-2", "chunk-3": "译文-3"}

        def fake_translate(chunk, lang, config):
            with lock:
                state["in_flight"] += 1
                state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
            time.sleep(delays[chunk])
            with lock:
                state["in_flight"] -= 1
            return outputs[chunk]

        monkeypatch.setattr("scrinium.translate._translate_chunk", fake_translate)

        result = translate_paper(paper_dir, cfg, target_lang="zh", force=True)

        assert result.ok is True
        assert state["max_in_flight"] > 1
        assert (paper_dir / "paper_zh.md").read_text(encoding="utf-8") == "译文-1\n\n译文-2\n\n译文-3"

    def test_translate_paper_portable_export_copies_images_and_preserves_links(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "Smith-2023-Test"
        images_dir = paper_dir / "images"
        paper_dir.mkdir(parents=True)
        images_dir.mkdir()
        (paper_dir / "paper.md").write_text("# Title\n\n![](images/fig1.png)\n", encoding="utf-8")
        (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
        (images_dir / "fig1.png").write_bytes(b"fake-image")

        cfg = SimpleNamespace(
            translate=SimpleNamespace(target_lang="zh", chunk_size=1000, concurrency=1),
            llm=SimpleNamespace(model="test-model"),
            workspace_dir=tmp_path / "workspace",
        )

        monkeypatch.setattr("scrinium.translate.detect_language", lambda text: "en")
        monkeypatch.setattr(
            "scrinium.translate._split_into_chunks", lambda text, chunk_size: ["# 标题\n\n![](images/fig1.png)\n"]
        )
        monkeypatch.setattr("scrinium.translate._translate_chunk", lambda chunk, lang, config: chunk)

        result = translate_paper(paper_dir, cfg, target_lang="zh", force=True, portable=True)

        portable_path = tmp_path / "workspace" / "translation-ws" / paper_dir.name / "paper_zh.md"
        assert result.ok is True
        assert result.portable_path == portable_path
        assert portable_path.exists()
        assert "](images/fig1.png)" in portable_path.read_text(encoding="utf-8")
        assert (tmp_path / "workspace" / "translation-ws" / paper_dir.name / "images" / "fig1.png").exists()
        assert (paper_dir / "paper_zh.md").exists()

    def test_translate_paper_portable_export_reuses_existing_translation(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "Smith-2023-Test"
        images_dir = paper_dir / "images"
        paper_dir.mkdir(parents=True)
        images_dir.mkdir()
        (paper_dir / "paper.md").write_text("# Title\n\n![](images/fig1.png)\n", encoding="utf-8")
        (paper_dir / "paper_zh.md").write_text("# 标题\n\n![](images/fig1.png)\n", encoding="utf-8")
        (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
        (images_dir / "fig1.png").write_bytes(b"fake-image")

        cfg = SimpleNamespace(
            translate=SimpleNamespace(target_lang="zh", chunk_size=1000, concurrency=1),
            llm=SimpleNamespace(model="test-model"),
            workspace_dir=tmp_path / "workspace",
        )

        monkeypatch.setattr("scrinium.translate.detect_language", lambda text: "en")
        monkeypatch.setattr(
            "scrinium.translate._translate_chunk",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not call llm")),
        )

        result = translate_paper(paper_dir, cfg, target_lang="zh", force=False, portable=True)

        portable_path = tmp_path / "workspace" / "translation-ws" / paper_dir.name / "paper_zh.md"
        assert result.ok is True
        assert result.path == paper_dir / "paper_zh.md"
        assert result.portable_path == portable_path
        assert portable_path.exists()
        assert (tmp_path / "workspace" / "translation-ws" / paper_dir.name / "images" / "fig1.png").exists()

    def test_translate_paper_does_not_write_output_when_all_chunks_fail(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "Smith-2023-Test"
        paper_dir.mkdir(parents=True)
        (paper_dir / "paper.md").write_text("This is an English paper.", encoding="utf-8")
        (paper_dir / "meta.json").write_text("{}", encoding="utf-8")

        cfg = SimpleNamespace(
            translate=SimpleNamespace(target_lang="zh", chunk_size=1000, concurrency=1),
            llm=SimpleNamespace(model="test-model"),
        )

        monkeypatch.setattr(
            "scrinium.translate._translate_chunk",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("llm unavailable")),
        )

        result = translate_paper(paper_dir, cfg, target_lang="zh", force=True)

        assert result.ok is False
        assert result.skip_reason == SKIP_ALL_CHUNKS_FAILED
        assert not (paper_dir / "paper_zh.md").exists()
        assert _translation_workdir(paper_dir, "zh").exists()

    def test_translate_chunk_with_retry_uses_exponential_backoff(self, monkeypatch):
        cfg = SimpleNamespace(llm=SimpleNamespace(timeout_clean=30))
        sleep_calls: list[float] = []
        attempts = {"count": 0}

        def fake_sleep(delay):
            sleep_calls.append(delay)

        def flaky_translate(text, lang, config, timeout=None):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise TimeoutError("network jitter")
            return "译文"

        monkeypatch.setattr("scrinium.translate.time.sleep", fake_sleep)
        monkeypatch.setattr("scrinium.translate._translate_chunk", flaky_translate)

        translated, used_attempts = _translate_chunk_with_retry("chunk", "zh", cfg)

        assert translated == "译文"
        assert used_attempts == 3
        assert sleep_calls == [1.0, 2.0]

    def test_translate_chunk_with_retry_uses_higher_retry_budget_on_exhaustion(self, monkeypatch):
        cfg = SimpleNamespace(llm=SimpleNamespace(timeout_clean=30))
        sleep_calls: list[float] = []
        attempts = {"count": 0}

        def fake_sleep(delay):
            sleep_calls.append(delay)

        def always_fail(text, lang, config, timeout=None):
            attempts["count"] += 1
            raise TimeoutError("still failing")

        monkeypatch.setattr("scrinium.translate.time.sleep", fake_sleep)
        monkeypatch.setattr("scrinium.translate._translate_chunk", always_fail)

        with pytest.raises(TimeoutError):
            _translate_chunk_with_retry("chunk", "zh", cfg)

        assert attempts["count"] == 5
        assert sleep_calls == [1.0, 2.0, 4.0, 8.0]

    def test_translate_paper_persists_parts_and_resumes_from_workdir(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "Smith-2023-Test"
        paper_dir.mkdir(parents=True)
        (paper_dir / "paper.md").write_text("Original text", encoding="utf-8")
        (paper_dir / "meta.json").write_text("{}", encoding="utf-8")

        cfg = SimpleNamespace(
            translate=SimpleNamespace(target_lang="zh", chunk_size=1000, concurrency=1),
            llm=SimpleNamespace(model="test-model"),
        )
        out_path = paper_dir / "paper_zh.md"
        workdir = _translation_workdir(paper_dir, "zh")
        progress_messages: list[str] = []

        monkeypatch.setattr("scrinium.translate.detect_language", lambda text: "en")
        monkeypatch.setattr(
            "scrinium.translate._split_into_chunks", lambda text, chunk_size: ["chunk-1", "chunk-2", "chunk-3"]
        )

        first_run_calls: list[str] = []

        def first_run_translate(chunk, lang, config):
            first_run_calls.append(chunk)
            if chunk == "chunk-1":
                return "译文-1"
            raise TimeoutError("chunk timeout")

        monkeypatch.setattr("scrinium.translate._translate_chunk", first_run_translate)

        first = translate_paper(
            paper_dir, cfg, target_lang="zh", force=True, progress_callback=progress_messages.append
        )

        assert first.ok is False
        assert first.partial is True
        assert first.path == out_path
        assert first.completed_chunks == 1
        assert first.total_chunks == 3
        assert first_run_calls[0] == "chunk-1"
        assert first_run_calls.count("chunk-1") == 1
        assert first_run_calls.count("chunk-2") >= 1
        assert out_path.read_text(encoding="utf-8") == "译文-1"
        assert workdir.exists()
        assert (workdir / "parts" / "000001.md").exists()
        assert (workdir / "state.json").exists()
        assert (workdir / "chunks.json").exists()
        assert any("开始翻译，共 3 块" in msg for msg in progress_messages)
        assert any("翻译进度: 1/3" in msg for msg in progress_messages)
        assert any("翻译在第 2/3 块中断" in msg for msg in progress_messages)

        second_run_calls: list[str] = []
        resume_messages: list[str] = []

        def second_run_translate(chunk, lang, config):
            second_run_calls.append(chunk)
            return {"chunk-2": "译文-2", "chunk-3": "译文-3"}[chunk]

        monkeypatch.setattr("scrinium.translate._translate_chunk", second_run_translate)

        second = translate_paper(
            paper_dir,
            cfg,
            target_lang="zh",
            force=False,
            progress_callback=resume_messages.append,
        )

        assert second.ok is True
        assert second.partial is False
        assert second.completed_chunks == 3
        assert second.total_chunks == 3
        assert second_run_calls == ["chunk-2", "chunk-3"]
        assert out_path.read_text(encoding="utf-8") == "译文-1\n\n译文-2\n\n译文-3"
        assert not workdir.exists()
        assert any("继续翻译：已完成 1/3 块" in msg for msg in resume_messages)
        assert any("翻译完成: 3/3 块" in msg for msg in resume_messages)

    def test_translate_paper_reuses_trailing_successful_chunks_after_gap(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "Smith-2023-Test"
        paper_dir.mkdir(parents=True)
        (paper_dir / "paper.md").write_text("Original text", encoding="utf-8")
        (paper_dir / "meta.json").write_text("{}", encoding="utf-8")

        cfg = SimpleNamespace(
            translate=SimpleNamespace(target_lang="zh", chunk_size=1000, concurrency=3),
            llm=SimpleNamespace(model="test-model"),
        )
        out_path = paper_dir / "paper_zh.md"
        workdir = _translation_workdir(paper_dir, "zh")

        monkeypatch.setattr("scrinium.translate.detect_language", lambda text: "en")
        monkeypatch.setattr(
            "scrinium.translate._split_into_chunks", lambda text, chunk_size: ["chunk-1", "chunk-2", "chunk-3"]
        )

        def first_run_translate(chunk, lang, config):
            if chunk == "chunk-2":
                raise TimeoutError("middle chunk timeout")
            return {"chunk-1": "译文-1", "chunk-3": "译文-3"}[chunk]

        monkeypatch.setattr("scrinium.translate._translate_chunk", first_run_translate)

        first = translate_paper(paper_dir, cfg, target_lang="zh", force=True)

        assert first.ok is False
        assert first.partial is True
        assert first.completed_chunks == 1
        assert out_path.read_text(encoding="utf-8") == "译文-1"
        assert (workdir / "parts" / "000001.md").exists()
        assert (workdir / "parts" / "000003.md").exists()

        second_run_calls: list[str] = []

        def second_run_translate(chunk, lang, config):
            second_run_calls.append(chunk)
            return {"chunk-2": "译文-2"}[chunk]

        monkeypatch.setattr("scrinium.translate._translate_chunk", second_run_translate)

        second = translate_paper(paper_dir, cfg, target_lang="zh", force=False)

        assert second.ok is True
        assert second_run_calls == ["chunk-2"]
        assert out_path.read_text(encoding="utf-8") == "译文-1\n\n译文-2\n\n译文-3"
        assert not workdir.exists()


class TestBatchTranslate:
    def test_batch_translate_splits_concurrency_budget_across_papers(self, tmp_path, monkeypatch):
        papers_dir = tmp_path / "papers"
        for name in ["Smith-2023-TestA", "Smith-2023-TestB"]:
            paper_dir = papers_dir / name
            paper_dir.mkdir(parents=True)
            (paper_dir / "meta.json").write_text(f'{{"id": "{name}"}}', encoding="utf-8")
            (paper_dir / "paper.md").write_text("Original text", encoding="utf-8")

        cfg = SimpleNamespace(
            translate=SimpleNamespace(target_lang="zh", chunk_size=1000, concurrency=4),
            llm=SimpleNamespace(model="test-model"),
        )

        received_chunk_workers: list[int | None] = []

        def fake_translate_paper(pdir, config, **kwargs):
            received_chunk_workers.append(kwargs.get("chunk_workers"))
            return SimpleNamespace(ok=True, partial=False, skip_reason="")

        monkeypatch.setattr("scrinium.translate.translate_paper", fake_translate_paper)

        stats = batch_translate(papers_dir, cfg, target_lang="zh", force=True)

        assert stats["translated"] == 2
        assert sorted(received_chunk_workers) == [2, 2]

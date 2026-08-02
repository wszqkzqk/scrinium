from __future__ import annotations

import os
import sqlite3
from types import SimpleNamespace

from scrinium import vectors
from scrinium.config import _build_config


def test_load_model_sets_hf_endpoint_before_sentence_transformers_import(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRINIUM_HF_ENDPOINT", raising=False)
    monkeypatch.delenv("HF_ENDPOINT", raising=False)

    cfg = _build_config(
        {
            "embed": {
                "source": "huggingface",
                "hf_endpoint": "https://hf-mirror.example",
                "device": "cpu",
                "model": "test-model",
            }
        },
        tmp_path,
    )

    seen: dict[str, str | None] = {}

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, device: str):
            self.model_name = model_name
            self.device = device

    def fake_import_module(name: str):
        assert name == "sentence_transformers"
        seen["hf_endpoint_at_import"] = os.environ.get("HF_ENDPOINT")
        return SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)

    monkeypatch.setattr(vectors.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(vectors, "_resolve_model_path", lambda *args: None)
    monkeypatch.setattr(vectors, "_remote_model_download_available", lambda *_args, **_kwargs: True)
    vectors._model_cache.clear()

    prev_hf_endpoint = os.environ.get("HF_ENDPOINT")
    try:
        model = vectors._load_model(cfg)
    finally:
        if prev_hf_endpoint is None:
            monkeypatch.delenv("HF_ENDPOINT", raising=False)
        else:
            monkeypatch.setenv("HF_ENDPOINT", prev_hf_endpoint)

    assert seen["hf_endpoint_at_import"] == "https://hf-mirror.example"
    assert model.model_name == "test-model"
    assert model.device == "cpu"


def test_load_model_overrides_modelscope_cache_from_cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELSCOPE_CACHE", "/preexisting-cache")
    cfg = _build_config(
        {
            "embed": {
                "source": "modelscope",
                "cache_dir": str(tmp_path / "cfg-cache"),
                "device": "cpu",
                "model": "test-model",
            }
        },
        tmp_path,
    )

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, device: str):
            self.model_name = model_name
            self.device = device

    monkeypatch.setattr(
        vectors.importlib,
        "import_module",
        lambda name: SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )
    monkeypatch.setattr(vectors, "_resolve_model_path", lambda *args: None)
    monkeypatch.setattr(vectors, "_remote_model_download_available", lambda *_args, **_kwargs: True)
    vectors._model_cache.clear()

    prev_modelscope_cache = os.environ.get("MODELSCOPE_CACHE")
    try:
        vectors._load_model(cfg)
        assert os.environ.get("MODELSCOPE_CACHE") == str(tmp_path / "cfg-cache")
    finally:
        if prev_modelscope_cache is None:
            monkeypatch.delenv("MODELSCOPE_CACHE", raising=False)
        else:
            monkeypatch.setenv("MODELSCOPE_CACHE", prev_modelscope_cache)


def test_resolve_model_path_prefers_existing_local_modelscope_cache(tmp_path, monkeypatch):
    model_dir = tmp_path / "Qwen" / "Qwen3-Embedding-0___6B"
    model_dir.mkdir(parents=True)
    for name in ("modules.json", "model.safetensors", "config_sentence_transformers.json"):
        (model_dir / name).write_text("ok", encoding="utf-8")

    monkeypatch.delitem(os.environ, "HF_ENDPOINT", raising=False)

    path = vectors._resolve_model_path("Qwen/Qwen3-Embedding-0.6B", str(tmp_path), "modelscope")

    assert path == str(model_dir)


def test_load_model_fast_fails_when_remote_download_is_unreachable(tmp_path, monkeypatch):
    cfg = _build_config(
        {
            "embed": {
                "source": "huggingface",
                "device": "cpu",
                "model": "test-model",
            }
        },
        tmp_path,
    )

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, device: str):
            raise AssertionError("remote loader should not be attempted when preflight fails")

    monkeypatch.setattr(
        vectors.importlib,
        "import_module",
        lambda name: SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )
    monkeypatch.setattr(vectors, "_resolve_model_path", lambda *args: None)
    monkeypatch.setattr(vectors, "_remote_model_download_available", lambda *_args, **_kwargs: False)
    vectors._model_cache.clear()

    try:
        vectors._load_model(cfg)
    except RuntimeError as exc:
        assert "HuggingFace" in str(exc) or "Hugging Face" in str(exc)
    else:
        raise AssertionError("expected _load_model to fail fast when remote preflight is unreachable")


def test_build_vectors_auto_rebuild_on_signature_change(tmp_papers, tmp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(vectors, "_embed_batch", lambda texts, cfg=None: [[0.1, 0.2, 0.3] for _ in texts])

    cfg_local = _build_config(
        {
            "embed": {
                "provider": "local",
                "model": "local-test-model",
                "source": "huggingface",
                "device": "cpu",
            }
        },
        tmp_path,
    )
    n1 = vectors.build_vectors(tmp_papers, tmp_db, cfg=cfg_local)
    assert n1 == 2

    with sqlite3.connect(tmp_db) as conn:
        sig1 = conn.execute("SELECT value FROM vector_metadata WHERE key='embed_signature'").fetchone()[0]
        count1 = conn.execute("SELECT COUNT(*) FROM paper_vectors").fetchone()[0]
    assert sig1.startswith("local::local-test-model::")
    assert count1 == 2

    cfg_cloud = _build_config(
        {
            "embed": {
                "provider": "openai-compat",
                "model": "text-embedding-3-small",
                "api_base": "https://api.example.com/v1",
                "api_key": "embed-key",
            }
        },
        tmp_path,
    )
    n2 = vectors.build_vectors(tmp_papers, tmp_db, cfg=cfg_cloud)
    assert n2 == 2  # full rebuild after signature change

    with sqlite3.connect(tmp_db) as conn:
        sig2 = conn.execute("SELECT value FROM vector_metadata WHERE key='embed_signature'").fetchone()[0]
        count2 = conn.execute("SELECT COUNT(*) FROM paper_vectors").fetchone()[0]
    assert sig2 == "openai-compat::text-embedding-3-small::https://api.example.com/v1"
    assert count2 == 2


def test_build_vectors_provider_none_clears_vectors(tmp_papers, tmp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(vectors, "_embed_batch", lambda texts, cfg=None: [[0.1, 0.2, 0.3] for _ in texts])

    cfg_local = _build_config(
        {
            "embed": {
                "provider": "local",
                "model": "local-test-model",
                "source": "huggingface",
                "device": "cpu",
            }
        },
        tmp_path,
    )
    assert vectors.build_vectors(tmp_papers, tmp_db, cfg=cfg_local) == 2

    cfg_none = _build_config({"embed": {"provider": "none"}}, tmp_path)
    assert vectors.build_vectors(tmp_papers, tmp_db, cfg=cfg_none) == 0

    with sqlite3.connect(tmp_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM paper_vectors").fetchone()[0]
        sig = conn.execute("SELECT value FROM vector_metadata WHERE key='embed_signature'").fetchone()[0]

    assert count == 0
    assert sig == "none"


def test_resolve_model_path_announces_download_when_model_not_cached(tmp_path, monkeypatch):
    import modelscope

    messages: list[str] = []
    monkeypatch.setattr(vectors, "ui", lambda msg="", *args: messages.append(msg))
    monkeypatch.setattr(vectors, "_find_local_model_path", lambda *args: None)

    calls: list[bool] = []

    def fake_snapshot_download(model_name, cache_dir=None, local_files_only=False):
        calls.append(local_files_only)
        if local_files_only:
            raise RuntimeError("not cached")
        return str(tmp_path / "downloaded-model")

    monkeypatch.setattr(modelscope, "snapshot_download", fake_snapshot_download)

    path = vectors._resolve_model_path("Qwen/Qwen3-Embedding-0.6B", str(tmp_path), "modelscope")

    assert path == str(tmp_path / "downloaded-model")
    # Cache probe (local_files_only=True) ran before the real download.
    assert calls == [True, False]
    assert any("首次运行需下载嵌入模型" in m for m in messages)


def test_resolve_model_path_no_download_notice_when_model_cached(tmp_path, monkeypatch):
    import modelscope

    messages: list[str] = []
    monkeypatch.setattr(vectors, "ui", lambda msg="", *args: messages.append(msg))
    monkeypatch.setattr(vectors, "_find_local_model_path", lambda *args: str(tmp_path / "model"))

    def fail_snapshot_download(*args, **kwargs):
        raise AssertionError("should not touch the network when the model is cached")

    monkeypatch.setattr(modelscope, "snapshot_download", fail_snapshot_download)

    path = vectors._resolve_model_path("Qwen/Qwen3-Embedding-0.6B", str(tmp_path), "modelscope")

    assert path == str(tmp_path / "model")
    assert not messages


def test_gpu_profile_read_path_prefers_new_with_legacy_fallback(tmp_path, monkeypatch):
    new_file = tmp_path / "new" / "gpu_profile.json"
    legacy_file = tmp_path / "legacy" / "gpu_profile.json"
    monkeypatch.setattr(vectors, "_GPU_PROFILE_FILE", new_file)
    monkeypatch.setattr(vectors, "_LEGACY_GPU_PROFILE_FILE", legacy_file)

    # Neither exists: default to the new location
    assert vectors._gpu_profile_read_path() == new_file

    # Only legacy exists: read from the legacy pre-fork location
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text("{}", encoding="utf-8")
    assert vectors._gpu_profile_read_path() == legacy_file

    # Both exist: the new location wins
    new_file.parent.mkdir(parents=True)
    new_file.write_text("{}", encoding="utf-8")
    assert vectors._gpu_profile_read_path() == new_file

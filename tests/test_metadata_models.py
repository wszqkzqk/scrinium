"""Tests for scrinium.ingest.metadata._models session configuration."""

from __future__ import annotations

from scrinium.ingest.metadata._models import SESSION, configure_s2_session


class TestConfigureS2Session:
    def test_clears_header_when_key_is_empty(self):
        original = SESSION.headers.get("x-api-key")

        try:
            SESSION.headers.pop("x-api-key", None)

            configure_s2_session("test-key")
            assert SESSION.headers.get("x-api-key") == "test-key"

            configure_s2_session("")
            assert "x-api-key" not in SESSION.headers
        finally:
            if original is None:
                SESSION.headers.pop("x-api-key", None)
            else:
                SESSION.headers["x-api-key"] = original

"""Tests for the WebSocket Origin check.

A Browser-initiated WebSocket handshake always carries an
``Origin`` header. A non-browser client (curl, an internal load
test) generally omits it. We treat a missing Origin as a
non-browser call (let it through) and compare a present Origin
against the configured allowlist.
"""

from __future__ import annotations

import pytest

from nhc.web.config import WebConfig
from nhc.web.ws import _origin_allowed


def _cfg(external_url: str = "") -> WebConfig:
    return WebConfig(external_url=external_url)


class TestOriginAllowed:
    def test_no_origin_header_allowed(self):
        """Non-browser client, nothing to cross-site-hijack."""
        assert _origin_allowed(None, _cfg())
        assert _origin_allowed("", _cfg())

    def test_localhost_always_allowed(self):
        assert _origin_allowed("http://localhost:5000", _cfg())
        assert _origin_allowed("http://localhost", _cfg())
        assert _origin_allowed("http://127.0.0.1:8080", _cfg())
        assert _origin_allowed("https://127.0.0.1", _cfg())

    def test_external_url_host_allowed(self):
        cfg = _cfg("https://nhc-game.duckdns.org")
        assert _origin_allowed("https://nhc-game.duckdns.org", cfg)
        # With a port, still matches by hostname.
        assert _origin_allowed(
            "https://nhc-game.duckdns.org:443", cfg,
        )

    def test_foreign_origin_rejected(self):
        cfg = _cfg("https://nhc-game.duckdns.org")
        assert not _origin_allowed("https://evil.example.com", cfg)
        assert not _origin_allowed(
            "https://nhc-game.duckdns.org.evil.example.com", cfg,
        )

    def test_empty_external_url_only_allows_localhost(self):
        """Before ``external_url`` is configured, only dev origins
        are accepted — any public origin hitting the server is
        certainly not us."""
        cfg = _cfg("")
        assert _origin_allowed("http://localhost:5000", cfg)
        assert not _origin_allowed(
            "https://nhc-game.duckdns.org", cfg,
        )

    def test_malformed_origin_rejected(self):
        cfg = _cfg("https://nhc-game.duckdns.org")
        assert not _origin_allowed("not a url", cfg)
        assert not _origin_allowed("://missing-scheme", cfg)

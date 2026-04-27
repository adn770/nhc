"""Tests for the build-info badge surfaced on the welcome page.

The badge lets a deploying user verify at-a-glance which container
image is actually running. Source of truth: two env vars set by
deploy/update.sh at docker-build time (NHC_GIT_SHA, NHC_BUILD_TIME);
when unset, the helper falls back to a "dev" sentinel so the local
./server still renders cleanly.
"""

from __future__ import annotations

import pytest

from nhc.web.build_info import get_build_info


class TestGetBuildInfo:
    def test_returns_env_values_when_both_set(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("NHC_GIT_SHA", "abc1234")
        monkeypatch.setenv("NHC_BUILD_TIME", "2026-04-27T16:00:00Z")
        assert get_build_info() == {
            "sha": "abc1234",
            "time": "2026-04-27T16:00:00Z",
        }

    def test_returns_dev_sentinel_when_neither_set(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("NHC_GIT_SHA", raising=False)
        monkeypatch.delenv("NHC_BUILD_TIME", raising=False)
        assert get_build_info() == {"sha": "dev", "time": "dev"}

    def test_returns_partial_when_only_sha_set(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Build args are independent: forgetting one shouldn't
        # produce a confusing fallback for the other.
        monkeypatch.setenv("NHC_GIT_SHA", "deadbeef")
        monkeypatch.delenv("NHC_BUILD_TIME", raising=False)
        assert get_build_info() == {"sha": "deadbeef", "time": "dev"}

    def test_returns_partial_when_only_time_set(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("NHC_GIT_SHA", raising=False)
        monkeypatch.setenv("NHC_BUILD_TIME", "2026-04-27T16:00:00Z")
        assert get_build_info() == {
            "sha": "dev",
            "time": "2026-04-27T16:00:00Z",
        }


class TestWelcomePageBuildInfo:
    """The welcome page renders the build info as a small footer
    so the deployer can confirm at-a-glance which image is live.
    """

    def test_welcome_page_includes_build_info_element(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from nhc.web.app import create_app
        from nhc.web.config import WebConfig

        monkeypatch.setenv("NHC_GIT_SHA", "fa11ed")
        monkeypatch.setenv("NHC_BUILD_TIME", "2026-04-27T17:00:00Z")
        app = create_app(WebConfig(max_sessions=2))
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/")
            body = resp.data.decode()
        assert resp.status_code == 200
        assert 'id="build-info"' in body, (
            "welcome page must carry a #build-info element so the "
            "deployer can confirm which image is running"
        )
        assert "fa11ed" in body, "git sha must be visible"
        assert "2026-04-27T17:00:00Z" in body, (
            "build time must be visible"
        )

    def test_welcome_page_falls_back_to_dev_locally(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Without the env vars (local ./server), the badge still
        # renders — just with the "dev" sentinel. Delete the env
        # explicitly so the test is robust whether or not the host
        # shell carries them.
        from nhc.web.app import create_app
        from nhc.web.config import WebConfig

        monkeypatch.delenv("NHC_GIT_SHA", raising=False)
        monkeypatch.delenv("NHC_BUILD_TIME", raising=False)
        app = create_app(WebConfig(max_sessions=2))
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/")
            body = resp.data.decode()
        assert resp.status_code == 200
        assert 'id="build-info"' in body
        # "dev" sentinel appears at least once (sha or time slot).
        assert "dev" in body

"""Regression tests for concurrent game initialization.

Reproduces the "game initialization failed" bug a user hit when a
second player started a game while another was already active. The
root causes were:

1. ``asyncio.new_event_loop() + run_until_complete`` inside a gevent
   worker without ``set_event_loop`` — racy when two greenlets enter
   the same handler.
2. CPU-bound generation running inline on the single gevent worker,
   starving other requests.

These tests exercise the Flask test client with multiple concurrent
``POST /api/game/new`` requests and assert every one succeeds.
"""

from __future__ import annotations

import threading

from nhc.web.app import create_app
from nhc.web.config import WebConfig


def _make_app(tmp_path, max_sessions=8):
    config = WebConfig(max_sessions=max_sessions, data_dir=tmp_path)
    app = create_app(config)
    app.config["TESTING"] = True
    # Disable the per-IP rate limiter for this test so we can send
    # many requests from the same client without hitting 429.
    import nhc.web.app as app_mod
    app_mod._RateLimiter.is_allowed = lambda self, ip: True
    return app


class TestConcurrentGameNew:
    def test_two_sequential_game_new_succeed(self, tmp_path):
        """Baseline: after fixing the asyncio bug, two sequential
        game_new calls in the same worker both succeed."""
        app = _make_app(tmp_path)
        try:
            with app.test_client() as c:
                r1 = c.post("/api/game/new", json={})
                r2 = c.post("/api/game/new", json={})
            assert r1.status_code == 201, r1.get_json()
            assert r2.status_code == 201, r2.get_json()
            assert r1.get_json()["session_id"] != r2.get_json()["session_id"]
        finally:
            app.config["GEN_POOL"].shutdown(wait=True)

    def test_concurrent_game_new_from_threads(self, tmp_path):
        """Two threads each POST /api/game/new. Both must succeed.

        This reproduces the multi-session failure: before the fix,
        one or both requests returned HTTP 500 "game initialization
        failed" because of asyncio loop state races.
        """
        app = _make_app(tmp_path, max_sessions=8)
        results: list[tuple[int, dict]] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def _worker():
            try:
                with app.test_client() as c:
                    resp = c.post("/api/game/new", json={})
                    with lock:
                        results.append((resp.status_code, resp.get_json()))
            except BaseException as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(4)]
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)
        finally:
            app.config["GEN_POOL"].shutdown(wait=True)

        assert not errors, f"worker errors: {errors!r}"
        assert len(results) == 4
        for status, body in results:
            assert status == 201, body
        sids = {body["session_id"] for _, body in results}
        assert len(sids) == 4, "expected 4 distinct session_ids"

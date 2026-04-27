"""Tests for the IR Phase 0.7 PNG stepping-stone endpoint.

``GET /api/game/<sid>/floor/<svg_id>.png`` rasterises the cached
floor SVG via resvg-py. Today the route is a thin
``svg → resvg → png`` shim; once Phase 1 lands the IR emitter,
the route routes through the IR; once Phase 5 ships ``tiny-skia``,
resvg-py is dropped and the route becomes ``IR → tiny-skia → PNG``.

These tests pin the public contract (URL shape, headers, error
codes) so the later transitions don't accidentally break a client
caching at the URL level.
"""

from __future__ import annotations

import pytest

from tests.unit.test_web_api import (   # noqa: F401  (fixture reuse)
    client_with_data_dir,
    _register_player,
)


resvg_py = pytest.importorskip(
    "resvg_py",
    reason=(
        "resvg-py not installed — required for the Phase 0.7 PNG "
        "stepping-stone endpoint; see requirements.txt"
    ),
)


def _new_session(client) -> tuple[str, str]:
    """Spin up a session and return (session_id, floor_svg_id)."""
    token, _pid = _register_player(client)
    resp = client.post(
        "/api/game/new",
        json={"player_token": token, "world": "dungeon"},
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    sid = resp.get_json()["session_id"]

    sessions = client.application.config["SESSIONS"]
    session = sessions.get(sid)
    assert session is not None, "session not registered"
    svg_id = session.game.renderer.floor_svg_id
    assert svg_id, "renderer did not populate floor_svg_id"
    return sid, svg_id


def test_png_endpoint_returns_png_with_cache_header(client_with_data_dir):
    sid, svg_id = _new_session(client_with_data_dir)
    resp = client_with_data_dir.get(f"/api/game/{sid}/floor/{svg_id}.png")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "image/png"
    assert resp.headers["Cache-Control"] == "public, max-age=604800"
    body = resp.get_data()
    assert body[:8] == b"\x89PNG\r\n\x1a\n", "response is not a PNG"


def test_png_endpoint_missing_session_returns_404(client_with_data_dir):
    resp = client_with_data_dir.get("/api/game/no-such-sid/floor/abc.png")
    assert resp.status_code == 404


def test_png_endpoint_missing_svg_id_returns_404(client_with_data_dir):
    sid, _ = _new_session(client_with_data_dir)
    resp = client_with_data_dir.get(
        f"/api/game/{sid}/floor/not-a-valid-uuid.png"
    )
    assert resp.status_code == 404

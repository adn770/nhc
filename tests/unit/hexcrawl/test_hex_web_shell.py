"""HTML shell and hextile static-asset route for hex mode.

These tests cover the web-side plumbing that M-1.8 lands:

* the index template contains the five hex canvas layers in the
  right z-order;
* the hex_map.js module is included;
* a /hextiles/<path> Flask route serves files from the project-root
  hextiles/ directory (gitignored asset pack, scp'd in production).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from nhc.web.app import create_app
from nhc.web.config import WebConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client(tmp_path):
    config = WebConfig(max_sessions=4, data_dir=tmp_path)
    app = create_app(config)
    app.config["TESTING"] = True
    return app.test_client(), app


# ---------------------------------------------------------------------------
# Canvas stack on the index template
# ---------------------------------------------------------------------------


_HEX_CANVAS_IDS = [
    "hex-base-canvas",
    "hex-fog-canvas",
    "hex-feature-canvas",
    "hex-entity-canvas",
    "hex-debug-canvas",
]


def test_index_includes_hex_canvas_stack(tmp_path) -> None:
    c, _app = _client(tmp_path)
    resp = c.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    for canvas_id in _HEX_CANVAS_IDS:
        assert canvas_id in html, (
            f"missing hex canvas id {canvas_id!r} in index template"
        )


def test_index_hex_canvases_in_correct_z_order(tmp_path) -> None:
    c, _app = _client(tmp_path)
    html = c.get("/").get_data(as_text=True)
    # DOM order matters: base behind fog behind features behind
    # entities behind debug.
    positions = [html.index(f'id="{cid}"') for cid in _HEX_CANVAS_IDS]
    assert positions == sorted(positions), (
        f"hex canvas elements out of order in HTML: {positions}"
    )


def test_index_includes_hex_map_js(tmp_path) -> None:
    c, _app = _client(tmp_path)
    html = c.get("/").get_data(as_text=True)
    assert "hex_map.js" in html


# ---------------------------------------------------------------------------
# /hextiles/ static route
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_hextiles_route_serves_existing_file(tmp_path) -> None:
    # Pick any file that exists in the project's hextiles directory
    # (the dir is gitignored but developers have it locally).
    hextiles = _project_root() / "hextiles"
    candidates = list(hextiles.glob("*.png"))
    if not candidates:
        candidates = list(hextiles.rglob("*.png"))
    if not candidates:
        pytest.skip("hextiles/ not populated on this machine")
    sample = candidates[0].relative_to(hextiles)
    c, _app = _client(tmp_path)
    resp = c.get(f"/hextiles/{sample.as_posix()}")
    assert resp.status_code == 200
    assert resp.content_type.startswith("image/")


def test_hextiles_route_returns_404_for_missing(tmp_path) -> None:
    c, _app = _client(tmp_path)
    resp = c.get("/hextiles/nope/does-not-exist.png")
    assert resp.status_code == 404


def test_hextiles_route_rejects_path_traversal(tmp_path) -> None:
    c, _app = _client(tmp_path)
    # Flask's send_from_directory normalises path and refuses to
    # escape the base directory. Regardless of the exact response,
    # we assert the file is not served.
    resp = c.get("/hextiles/../README.md")
    assert resp.status_code in (403, 404)
    if resp.status_code == 200:
        assert False, "path traversal must not succeed"

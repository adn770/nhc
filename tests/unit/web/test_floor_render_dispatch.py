"""NIR-only floor render dispatch (A3).

The game always renders the floor browser-side from the NIR. The
client must fetch ``.nir`` and rasterise it via the WASM dispatcher,
keeping the PNG path *only* as a WASM-load-failure fallback. The
legacy svg/png render-mode selector (the ``render-mode`` meta tag and
``map.js``'s ``_renderMode`` / ``_loadFloorSVG``) is gone.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAP_JS = PROJECT_ROOT / "nhc" / "web" / "static" / "js" / "map.js"
INDEX_HTML = (
    PROJECT_ROOT / "nhc" / "web" / "templates" / "index.html"
)


def test_index_has_no_render_mode_meta():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'name="render-mode"' not in html


def test_map_js_has_no_render_mode_selector():
    src = MAP_JS.read_text(encoding="utf-8")
    assert "_renderMode" not in src
    assert "_loadFloorSVG" not in src
    assert 'meta[name="render-mode"]' not in src


def test_set_floor_url_always_uses_nir():
    src = MAP_JS.read_text(encoding="utf-8")
    assert '_loadFloorWASM(url + ".nir")' in src


def test_png_retained_as_failure_fallback():
    """The PNG path stays as the WASM-load-failure fallback so a
    broken bundle doesn't strand the player on a blank screen."""
    src = MAP_JS.read_text(encoding="utf-8")
    assert "_loadFloorPNG" in src
    assert '_loadFloorPNG(url + ".png")' in src

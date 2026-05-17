"""The Dyson hatch tile ships as a static base64 SVG data URI in
a committed JS module, not the old /api/hatch.svg endpoint."""

import base64
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_JS = _ROOT / "nhc" / "web" / "static" / "js" / "hatch_pattern.js"
_INDEX = _ROOT / "nhc" / "web" / "templates" / "index.html"


def test_hatch_pattern_js_exists():
    assert _JS.is_file(), "run `make hatch-pattern`"


def test_defines_svg_data_uri_global():
    text = _JS.read_text(encoding="utf-8")
    m = re.search(
        r'window\.NHC_HATCH_URI\s*=\s*"'
        r'data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)"',
        text,
    )
    assert m, "hatch_pattern.js must set window.NHC_HATCH_URI"
    decoded = base64.b64decode(m.group(1))
    assert decoded.lstrip().startswith(b"<svg"), (
        "data URI must decode to an SVG document"
    )


def test_index_loads_hatch_pattern_before_map():
    html = _INDEX.read_text(encoding="utf-8")
    assert "hatch_pattern.js" in html, (
        "index.html must include the hatch_pattern.js script"
    )
    assert html.index("hatch_pattern.js") < html.index("map.js"), (
        "hatch_pattern.js must load before map.js uses the global"
    )

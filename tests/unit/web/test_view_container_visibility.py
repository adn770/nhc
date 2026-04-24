"""Each view-switch helper in ``hex_map.js`` must hide the two
containers it isn't activating.

The five views split across three DOM containers: ``hex-container``
(hex only), ``flower-container`` (flower only), and
``map-container`` (site / structure / dungeon shared). The three
helpers ``_showHexOverland`` / ``_showMapView`` / the flower WS
handler each need to **reveal their container and hide the other
two** -- otherwise a view stacks on top of the previous one and
the UI looks stuck.

This regression test parses ``hex_map.js`` and asserts the two
``_show*`` helpers each contain three ``classList`` calls: one
``remove("hidden")`` on their own container plus two
``add("hidden")`` calls on the others. The live bug this guards
against: pressing Shift-L on the flower view dispatched
``flower_exit``, the server emitted ``state_hex``, the handler
called ``_showHexOverland`` -- which only hid ``map-container``
and forgot ``flower-container``. Flower stayed visible on top of
hex and the player thought L did nothing.

See ``design/views.md`` for the five-view hierarchy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
HEX_MAP_JS = PROJECT_ROOT / "nhc" / "web" / "static" / "js" / "hex_map.js"


def _extract_function_body(source: str, name: str) -> str:
    """Pull out the body of a top-level JS function declaration.
    Brace-counts from the opening ``{`` to the matching close."""
    pattern = re.compile(
        rf"function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{",
        re.MULTILINE,
    )
    m = pattern.search(source)
    if m is None:
        raise AssertionError(
            f"function {name!r} not found in hex_map.js"
        )
    i = m.end()
    depth = 1
    while i < len(source) and depth > 0:
        c = source[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return source[m.end(): i - 1]


OWN_CONTAINER = {
    "_showHexOverland": "hex-container",
    "_showMapView":     "map-container",
}


def _var_for_container(body: str, container_id: str) -> str | None:
    """Return the local JS variable name the helper binds to
    ``document.getElementById("<container_id>")``, or ``None`` if
    the helper doesn't reference that container."""
    m = re.search(
        rf'(?:const|let|var)\s+(\w+)\s*=\s*'
        rf'document\.getElementById\("{re.escape(container_id)}"\)',
        body,
    )
    return m.group(1) if m else None


@pytest.mark.parametrize("helper", sorted(OWN_CONTAINER))
def test_view_switch_helper_hides_other_containers(helper: str) -> None:
    source = HEX_MAP_JS.read_text()
    body = _extract_function_body(source, helper)
    own = OWN_CONTAINER[helper]
    others = {"hex-container", "flower-container", "map-container"} - {own}
    # The helper must REMOVE "hidden" from its own container...
    own_var = _var_for_container(body, own)
    assert own_var is not None, (
        f"{helper} does not reference its own container "
        f"{own!r} via document.getElementById"
    )
    own_remove = re.search(
        rf'{re.escape(own_var)}\.classList\.remove\("hidden"\)',
        body,
    )
    assert own_remove is not None, (
        f"{helper} must call {own_var}.classList.remove('hidden') "
        f"so its own view ({own!r}) becomes visible"
    )
    # ...and ADD "hidden" on the two others, otherwise the
    # outgoing view stacks over the incoming one.
    for other in sorted(others):
        other_var = _var_for_container(body, other)
        assert other_var is not None, (
            f"{helper} does not bind a variable for "
            f"{other!r}; it needs to hide that container "
            f"during the view switch. (Live bug: L on flower "
            f"sent state_hex, _showHexOverland ran but never "
            f"grabbed flower-container -- so flower stayed on "
            f"top of hex and the player thought nothing "
            f"happened.)"
        )
        other_add = re.search(
            rf'{re.escape(other_var)}\.classList\.add\("hidden"\)',
            body,
        )
        assert other_add is not None, (
            f"{helper} binds {other_var} for {other!r} but "
            f"never calls classList.add('hidden') on it. "
            f"Switching views must hide the old one or it "
            f"stacks over the new view."
        )

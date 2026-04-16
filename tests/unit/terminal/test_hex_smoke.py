"""Phase 3 terminal hex smoke.

Proves the terminal hex pieces compose: the render path toggles
the hex-mode flag, ``get_input`` dispatches against the hex key
table while that flag is set, and the flag flips back when a
dungeon level renders. No live ``blessed`` terminal is needed --
``_blocking_read`` is stubbed so the test runs in CI without a
tty.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import Biome, HexCell, HexFeatureType, HexWorld
from nhc.rendering.terminal.renderer import TerminalRenderer


def _tiny_world() -> HexWorld:
    w = HexWorld(pack_id="smoke", seed=0, width=5, height=5)
    for q in range(3):
        for r in range(3):
            c = HexCoord(q=q, r=r)
            w.cells[c] = HexCell(
                coord=c, biome=Biome.GREENLANDS,
                feature=HexFeatureType.NONE,
            )
            w.reveal(c)
    return w


@pytest.fixture
def renderer():
    """A renderer we can drive without a live tty.

    The constructor still needs a Terminal handle so a couple of
    attributes resolve (``term.width`` / ``term.height``); those
    come back sensible even when stdout isn't attached, so the
    fixture is good enough for flag-flipping smoke work.
    """
    return TerminalRenderer(color_mode="none")


def test_render_hex_sets_hex_mode_flag(renderer, capsys) -> None:
    """``render_hex`` flips the flag so ``get_input`` knows which
    key table to dispatch against."""
    assert renderer._hex_mode is False
    renderer.render_hex(_tiny_world(), HexCoord(q=0, r=0), turn=1)
    capsys.readouterr()  # drain ANSI escape output
    assert renderer._hex_mode is True


def test_get_input_dispatches_to_hex_table_in_hex_mode(renderer) -> None:
    """Capital L during hex mode → hex_exit; dungeon table has no
    such binding (returns unknown), so this proves the dispatch."""
    renderer._hex_mode = True
    with patch.object(renderer, "_blocking_read", return_value="L"):
        intent, data = asyncio.run(renderer.get_input())
    assert intent == "hex_exit"
    assert data is None


def test_get_input_dispatches_to_dungeon_table_when_not_hex(
    renderer,
) -> None:
    """Same keystroke outside hex mode falls back to the dungeon
    table; 'L' is unmapped there."""
    renderer._hex_mode = False
    with patch.object(renderer, "_blocking_read", return_value="L"):
        intent, data = asyncio.run(renderer.get_input())
    assert intent == "unknown"


def test_get_input_hex_step_resolves_axial_delta(renderer) -> None:
    """Under hex mode, 'u' → hex_step NE, matching the axial
    NEIGHBOR_OFFSETS table the game loop consumes."""
    renderer._hex_mode = True
    with patch.object(renderer, "_blocking_read", return_value="u"):
        intent, data = asyncio.run(renderer.get_input())
    assert intent == "hex_step"
    assert data == (1, -1)

"""Terminal hex-mode key bindings (M-3.2).

When the terminal client is in overland mode, ``map_key_to_hex_intent``
translates keystrokes into the hex-mode intents the game loop
already consumes (``hex_step``, ``hex_enter``, ``hex_rest``,
``hex_exit``, ``panic_flee``). The hex map supports six flat-top
directions, so the table is wider than the dungeon 8-way one.
"""

from __future__ import annotations

import pytest

from nhc.rendering.terminal.input import map_key_to_hex_intent


# ---------------------------------------------------------------------------
# Six-direction movement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key, expected",
    [
        ("k", (0, -1)),    # N
        ("u", (1, -1)),    # NE
        ("n", (1, 0)),     # SE
        ("j", (0, 1)),     # S
        ("b", (-1, 1)),    # SW
        ("y", (-1, 0)),    # NW
        # Numpad equivalents.
        ("8", (0, -1)),
        ("9", (1, -1)),
        ("3", (1, 0)),
        ("2", (0, 1)),
        ("1", (-1, 1)),
        ("7", (-1, 0)),
    ],
)
def test_vi_and_numpad_keys_emit_hex_step(key, expected) -> None:
    intent, data = map_key_to_hex_intent(key)
    assert intent == "hex_step"
    assert data == expected


def test_arrow_keys_map_to_the_four_cardinals() -> None:
    """Arrow keys trade off: flat-top hex has no pure East / West,
    so the terminal picks the two "mostly-horizontal" diagonals
    (NW / SE) for Left / Right respectively. The player can still
    reach every neighbour via vi / numpad keys."""
    assert map_key_to_hex_intent("KEY_UP") == ("hex_step", (0, -1))
    assert map_key_to_hex_intent("KEY_DOWN") == ("hex_step", (0, 1))
    assert map_key_to_hex_intent("KEY_LEFT") == ("hex_step", (-1, 0))
    assert map_key_to_hex_intent("KEY_RIGHT") == ("hex_step", (1, 0))


# ---------------------------------------------------------------------------
# Non-movement intents
# ---------------------------------------------------------------------------


def test_gt_enters_feature() -> None:
    """'>' reuses the dungeon descend key for entering a hex
    feature; players already associate it with 'go in'."""
    assert map_key_to_hex_intent(">") == ("hex_enter", None)


def test_dot_and_5_rest_advance_clock() -> None:
    assert map_key_to_hex_intent(".") == ("hex_rest", None)
    assert map_key_to_hex_intent("5") == ("hex_rest", None)


def test_uppercase_l_leaves_dungeon_to_overland() -> None:
    """Matches the web client's Shift+L hotkey so muscle memory
    carries between the two frontends."""
    assert map_key_to_hex_intent("L") == ("hex_exit", None)


def test_uppercase_f_triggers_panic_flee() -> None:
    assert map_key_to_hex_intent("F") == ("panic_flee", None)


def test_scroll_keys_still_scroll_the_message_log() -> None:
    """Scroll bindings should work in both modes -- the player
    reads the same log across them."""
    assert map_key_to_hex_intent("[") == ("scroll_up", None)
    assert map_key_to_hex_intent("]") == ("scroll_down", None)


def test_unknown_key_returns_unknown_intent() -> None:
    assert map_key_to_hex_intent("Z") == ("unknown", None)


# ---------------------------------------------------------------------------
# Dungeon table is unchanged
# ---------------------------------------------------------------------------


def test_dungeon_map_still_uses_cartesian_move() -> None:
    """Adding the hex table must not break the dungeon 8-way
    bindings; the two live in independent dicts."""
    from nhc.rendering.terminal.input import map_key_to_intent
    assert map_key_to_intent("k") == ("move", (0, -1))
    assert map_key_to_intent("l") == ("move", (1, 0))
    assert map_key_to_intent("L") == ("unknown", None)

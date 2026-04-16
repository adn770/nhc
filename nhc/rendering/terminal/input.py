"""Async keyboard input handler for terminal."""

from __future__ import annotations

# Key → (intent, data)
# Intent types: "move", "pickup", "use_item", "descend", "wait",
#               "scroll_up", "scroll_down", "quit", "unknown"
KEY_MAP: dict[str, tuple[str, tuple[int, int] | None]] = {
    # Arrow keys
    "KEY_UP":    ("move", (0, -1)),
    "KEY_DOWN":  ("move", (0, 1)),
    "KEY_LEFT":  ("move", (-1, 0)),
    "KEY_RIGHT": ("move", (1, 0)),
    # Vi keys
    "k": ("move", (0, -1)),
    "j": ("move", (0, 1)),
    "h": ("move", (-1, 0)),
    "l": ("move", (1, 0)),
    "y": ("move", (-1, -1)),
    "u": ("move", (1, -1)),
    "b": ("move", (-1, 1)),
    "n": ("move", (1, 1)),
    # Numpad (some terminals)
    "KEY_HOME":   ("move", (-1, -1)),
    "KEY_PGUP":   ("move", (1, -1)),
    "KEY_END":    ("move", (-1, 1)),
    "KEY_NPAGE":  ("move", (1, 1)),
    # Actions
    "g": ("pickup", None),
    ",": ("pickup", None),
    "i": ("inventory", None),
    "a": ("use_item", None),
    "q": ("quaff", None),
    "e": ("equip", None),
    "d": ("drop", None),
    "t": ("throw", None),
    "z": ("zap", None),
    "p": ("pick_lock", None),
    "f": ("force_door", None),
    "c": ("close_door", None),
    "D": ("dig", None),
    ">": ("descend", None),
    "<": ("ascend", None),
    ":": ("farlook", None),
    ".": ("wait", None),
    "5": ("wait", None),
    # Message scroll
    "[": ("scroll_up", None),
    "]": ("scroll_down", None),
    # Search adjacent tiles
    "s": ("search", None),
    # Help
    "?": ("help", None),
    # Mode toggle
    "\t": ("toggle_mode", None),
    "KEY_TAB": ("toggle_mode", None),
    # Henchman commands
    "G": ("give_item", None),
    "P": ("dismiss_henchman", None),
    # God mode: reveal full map
    "M": ("reveal_map", None),
    # Quit
    "Q": ("quit", None),
}


def map_key_to_intent(key_name: str) -> tuple[str, tuple[int, int] | None]:
    """Map a key name to a game intent."""
    return KEY_MAP.get(key_name, ("unknown", None))


# ── Hex-mode key map ──────────────────────────────────────────────────
# A separate dict so adding hex bindings doesn't perturb the 8-way
# dungeon movement table. Data tuples here are (dq, dr) axial
# deltas consumed by Game._process_hex_turn's hex_step branch.
#
# Six direction convention (matches HexCoord NEIGHBOR_OFFSETS):
#   N  (0, -1)   NE (1, -1)   SE (1, 0)
#   S  (0,  1)   SW (-1, 1)   NW (-1, 0)
HEX_KEY_MAP: dict[str, tuple[str, tuple[int, int] | None]] = {
    # Vi-style keys.
    "k": ("hex_step", (0, -1)),    # N
    "u": ("hex_step", (1, -1)),    # NE
    "n": ("hex_step", (1, 0)),     # SE
    "j": ("hex_step", (0, 1)),     # S
    "b": ("hex_step", (-1, 1)),    # SW
    "y": ("hex_step", (-1, 0)),    # NW
    # Numpad.
    "8": ("hex_step", (0, -1)),
    "9": ("hex_step", (1, -1)),
    "3": ("hex_step", (1, 0)),
    "2": ("hex_step", (0, 1)),
    "1": ("hex_step", (-1, 1)),
    "7": ("hex_step", (-1, 0)),
    # Arrow keys: flat-top hex has no pure E / W, so Left / Right
    # are the two "mostly-horizontal" neighbours (NW / SE).
    "KEY_UP":    ("hex_step", (0, -1)),
    "KEY_DOWN":  ("hex_step", (0, 1)),
    "KEY_LEFT":  ("hex_step", (-1, 0)),
    "KEY_RIGHT": ("hex_step", (1, 0)),
    # Actions.
    ">":  ("hex_enter", None),
    ".":  ("hex_rest", None),
    "5":  ("hex_rest", None),
    "L":  ("hex_exit", None),
    "F":  ("panic_flee", None),
    # Scroll bindings carry over.
    "[": ("scroll_up", None),
    "]": ("scroll_down", None),
    # Help / quit are always available.
    "?": ("help", None),
    "Q": ("quit", None),
    "\t": ("toggle_mode", None),
    "KEY_TAB": ("toggle_mode", None),
}


def map_key_to_hex_intent(
    key_name: str,
) -> tuple[str, tuple[int, int] | None]:
    """Map a key name to a hex-mode intent.

    Returns the same ``(intent, data)`` shape as
    :func:`map_key_to_intent` but from the hex-specific table,
    so the game loop's hex-turn handler can consume it without
    further translation.
    """
    return HEX_KEY_MAP.get(key_name, ("unknown", None))

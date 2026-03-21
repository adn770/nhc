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
    ">": ("descend", None),
    ".": ("wait", None),
    "5": ("wait", None),
    # Message scroll
    "[": ("scroll_up", None),
    "]": ("scroll_down", None),
    # Quit
    "q": ("quit", None),
    "Q": ("quit", None),
}


def map_key_to_intent(key_name: str) -> tuple[str, tuple[int, int] | None]:
    """Map a key name to a game intent."""
    return KEY_MAP.get(key_name, ("unknown", None))

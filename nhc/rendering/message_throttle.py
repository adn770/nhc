"""Throttle consecutive identical in-game messages.

Collapses runs of repeated player-facing messages so the
message panel doesn't drown in spam (e.g. ``You see a
villager`` firing every turn while the player explores).

The first message of a run is always shown. Every
``group_size`` subsequent duplicates collapse into a single
``(xN)`` rollup. When the run is broken by a different message
and at least 2 duplicates are buffered, a final ``(xN)`` rollup
is flushed before the new message; a lone trailing duplicate is
dropped silently.
"""

from __future__ import annotations


class MessageThrottle:
    """Stateful collapser for consecutive identical messages."""

    def __init__(self, group_size: int = 5) -> None:
        if group_size < 2:
            raise ValueError("group_size must be >= 2")
        self._group_size = group_size
        self._last: str | None = None
        self._pending = 0

    def feed(self, text: str) -> list[str]:
        """Return the messages that should actually be shown."""
        if self._last is not None and text == self._last:
            self._pending += 1
            if self._pending == self._group_size:
                self._pending = 0
                return [f"{text} (x{self._group_size})"]
            return []
        out: list[str] = []
        if self._last is not None and self._pending >= 2:
            out.append(f"{self._last} (x{self._pending})")
        out.append(text)
        self._last = text
        self._pending = 0
        return out

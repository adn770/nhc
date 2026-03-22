"""Narrative log for typed gameplay mode.

Replaces the simple message list with typed entries that distinguish
between narrative prose (from the GM) and mechanical outcomes (from ECS).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from blessed import Terminal


@dataclass
class LogEntry:
    """A single narrative log entry."""

    text: str
    type: str = "narrative"  # "narrative" or "mechanical"


class NarrativeLog:
    """Scrollable log with narrative and mechanical message types."""

    def __init__(self, max_entries: int = 200) -> None:
        self.entries: list[LogEntry] = []
        self.scroll_offset: int = 0  # 0 = showing latest
        self._max = max_entries

    def add(self, text: str, type: str = "narrative") -> None:
        """Add an entry to the log."""
        self.entries.append(LogEntry(text=text, type=type))
        if len(self.entries) > self._max:
            self.entries = self.entries[-self._max:]
        self.scroll_offset = 0

    def add_narrative(self, text: str) -> None:
        self.add(text, "narrative")

    def add_mechanical(self, text: str) -> None:
        self.add(text, "mechanical")

    def scroll(self, direction: int) -> None:
        """Scroll: +1 = older, -1 = newer."""
        self.scroll_offset = max(0, self.scroll_offset + direction)

    @property
    def messages(self) -> list[str]:
        """Plain text list for compatibility with classic mode."""
        return [e.text for e in self.entries]


def render_narrative_log(
    term: "Terminal",
    y: int,
    width: int,
    height: int,
    entries: list[LogEntry],
    scroll_offset: int,
) -> str:
    """Render the narrative log area."""
    output = ""

    # Word-wrap entries into display lines
    lines: list[tuple[str, str]] = []  # (text, type)
    for entry in entries:
        for raw_line in entry.text.split("\n"):
            # Simple word wrap
            while len(raw_line) > width - 2:
                split = raw_line[:width - 2].rfind(" ")
                if split <= 0:
                    split = width - 2
                lines.append((raw_line[:split], entry.type))
                raw_line = raw_line[split:].lstrip()
            if raw_line:
                lines.append((raw_line, entry.type))

    # Apply scroll offset (from bottom)
    end = len(lines) - scroll_offset
    start = max(0, end - height)
    visible = lines[start:end]

    # Pad to fill height
    while len(visible) < height:
        visible.insert(0, ("", "narrative"))

    for i, (text, msg_type) in enumerate(visible):
        padded = f" {text}".ljust(width)
        if msg_type == "mechanical":
            colored = term.bright_black(padded)
        else:
            colored = padded
        output += term.move_xy(0, y + i) + colored

    return output

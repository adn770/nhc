"""Text input widget for typed gameplay mode.

Provides line editing (insert, delete, cursor movement, home/end)
and input history (up/down arrows, last 20 entries).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from blessed import Terminal


_HISTORY_PATH = "~/.cache/nhc/input_history.json"


class TextInput:
    """Single-line text editor with history."""

    def __init__(self, max_history: int = 20) -> None:
        self.text: str = ""
        self.cursor: int = 0
        self.history: list[str] = []
        self._history_idx: int = -1
        self._max_history = max_history
        self._stash: str = ""  # stash current text when browsing history
        self._load_history()

    def insert(self, ch: str) -> None:
        """Insert a character or string at the cursor position."""
        self.text = self.text[:self.cursor] + ch + self.text[self.cursor:]
        self.cursor += len(ch)

    def backspace(self) -> None:
        if self.cursor > 0:
            self.text = self.text[:self.cursor - 1] + self.text[self.cursor:]
            self.cursor -= 1

    def delete(self) -> None:
        if self.cursor < len(self.text):
            self.text = self.text[:self.cursor] + self.text[self.cursor + 1:]

    def move_left(self) -> None:
        self.cursor = max(0, self.cursor - 1)

    def move_right(self) -> None:
        self.cursor = min(len(self.text), self.cursor + 1)

    def home(self) -> None:
        self.cursor = 0

    def end(self) -> None:
        self.cursor = len(self.text)

    def clear(self) -> None:
        self.text = ""
        self.cursor = 0
        self._history_idx = -1

    def history_up(self) -> None:
        """Navigate to older history entry."""
        if not self.history:
            return
        if self._history_idx == -1:
            self._stash = self.text
            self._history_idx = len(self.history) - 1
        elif self._history_idx > 0:
            self._history_idx -= 1
        else:
            return
        self.text = self.history[self._history_idx]
        self.cursor = len(self.text)

    def history_down(self) -> None:
        """Navigate to newer history entry."""
        if self._history_idx == -1:
            return
        if self._history_idx < len(self.history) - 1:
            self._history_idx += 1
            self.text = self.history[self._history_idx]
        else:
            self._history_idx = -1
            self.text = self._stash
        self.cursor = len(self.text)

    def submit(self) -> str:
        """Submit the current text, add to history, and reset."""
        text = self.text.strip()
        if text:
            self.history.append(text)
            if len(self.history) > self._max_history:
                self.history = self.history[-self._max_history:]
            self._save_history()
        self.text = ""
        self.cursor = 0
        self._history_idx = -1
        return text

    def _load_history(self) -> None:
        """Load input history from disk."""
        import json
        from pathlib import Path
        path = Path(_HISTORY_PATH).expanduser()
        if path.exists():
            try:
                self.history = json.loads(path.read_text())[-self._max_history:]
            except (json.JSONDecodeError, OSError):
                pass

    def _save_history(self) -> None:
        """Persist input history to disk."""
        import json
        from pathlib import Path
        path = Path(_HISTORY_PATH).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(json.dumps(self.history[-self._max_history:]))
        except OSError:
            pass


def render_input_line(
    term: "Terminal",
    y: int,
    width: int,
    text: str,
    cursor: int,
) -> str:
    """Render the input line with prompt and cursor."""
    prompt = term.bright_yellow("> ")
    # Visible portion of text (scroll if longer than width)
    max_text = width - 4  # "> " + cursor + margin
    if cursor > max_text:
        offset = cursor - max_text
        visible = text[offset:offset + max_text]
        cursor_pos = max_text
    else:
        visible = text[:max_text]
        cursor_pos = cursor

    # Build the line with cursor indicator
    before = visible[:cursor_pos]
    cursor_char = visible[cursor_pos] if cursor_pos < len(visible) else " "
    after = visible[cursor_pos + 1:] if cursor_pos < len(visible) else ""

    line = prompt + before + term.reverse(cursor_char) + after
    padding = " " * max(0, width - len("> ") - len(visible) - 1)

    return term.move_xy(0, y) + line + padding

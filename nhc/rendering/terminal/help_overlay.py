"""Scrollable help overlay that renders a markdown document."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nhc.i18n import current_lang

if TYPE_CHECKING:
    from blessed import Terminal

_DOCS_DIR = Path(__file__).parent.parent.parent.parent / "docs"

# Border color: sky blue via RGB
_BORDER_RGB = (80, 140, 210)


def _load_help() -> list[str]:
    """Load the help document for the active language, line by line."""
    lang = current_lang()
    path = _DOCS_DIR / f"help_{lang}.md"
    if not path.exists():
        path = _DOCS_DIR / "help_en.md"
    return path.read_text().splitlines()


def show_help(term: "Terminal") -> None:
    """Display a scrollable help overlay. Blocks until ESC/q/?."""
    from nhc.rendering.terminal.renderer import (
        CHROME_HEIGHT_CLASSIC,
        STATUS_HEIGHT,
    )

    lines = _load_help()
    scroll = 0

    # Fit inside the map zone: leave chrome at the bottom untouched
    # and 1 empty line above + 1 below the box
    map_h = term.height - CHROME_HEIGHT_CLASSIC
    view_h = max(5, map_h - 4)  # 1 above + 1 top border + content + 1 bot border + 1 below
    max_scroll = max(0, len(lines) - view_h)

    while True:
        _draw(term, lines, scroll, view_h)
        with term.cbreak():
            val = term.inkey(timeout=None)
            key = val.name if val.is_sequence else str(val)

        if key in ("KEY_ESCAPE", "\x1b", "q", "Q", "?"):
            break
        elif key in ("KEY_UP", "k"):
            scroll = max(0, scroll - 1)
        elif key in ("KEY_DOWN", "j"):
            scroll = min(max_scroll, scroll + 1)
        elif key in ("KEY_PGUP", "KEY_HOME"):
            scroll = max(0, scroll - view_h)
        elif key in ("KEY_NPAGE", "KEY_END"):
            scroll = min(max_scroll, scroll + view_h)
        elif key == " ":
            scroll = min(max_scroll, scroll + view_h)


def _border(term: "Terminal", text: str) -> str:
    """Apply border color to text."""
    return term.color_rgb(*_BORDER_RGB)(text)


def _draw(
    term: "Terminal", lines: list[str], scroll: int, view_h: int,
) -> None:
    """Render the help overlay as a centered box over the map zone."""
    box_w = min(term.width - 4, 112)
    box_x = (term.width - box_w) // 2
    box_y = 1
    inner_w = box_w - 4  # │ + space + content + space + │

    output = ""

    from nhc.rendering.terminal.themes import get_theme
    theme = get_theme()

    # Top border
    output += term.move_xy(box_x, box_y)
    output += _border(term,
        theme.box_tl + theme.box_h * (box_w - 2) + theme.box_tr)

    # Content lines
    visible = lines[scroll:scroll + view_h]
    for i in range(view_h):
        y = box_y + 1 + i
        if i < len(visible):
            rendered = _render_md_line(term, visible[i], inner_w)
        else:
            rendered = " " * inner_w
        output += term.move_xy(box_x, y)
        output += (_border(term, theme.box_v)
                   + " " + rendered + " "
                   + _border(term, theme.box_v))

    # Scroll indicator
    total = len(lines)
    if total > view_h:
        pct = int(100 * scroll / max(1, total - view_h))
        indicator = f"  {scroll + 1}-{min(scroll + view_h, total)}/{total} ({pct}%)"
    else:
        indicator = ""

    # Bottom border
    footer_text = "ESC/q: close  ↑↓: scroll  PgUp/PgDn: page" + indicator
    max_text = box_w - 4
    footer_text = footer_text[:max_text]
    fill_total = max(0, max_text - len(footer_text))
    left_fill = fill_total // 2
    right_fill = fill_total - left_fill
    footer_colored = _border(term,
        theme.box_h * left_fill + " " + footer_text
        + " " + theme.box_h * right_fill
    )

    bot_y = box_y + 1 + view_h
    output += term.move_xy(box_x, bot_y)
    output += (_border(term, theme.box_bl)
               + footer_colored
               + _border(term, theme.box_br))

    # Empty lines below the box (clear any leftover from previous draw)
    for dy in range(1, 3):
        output += term.move_xy(box_x, bot_y + dy) + " " * box_w

    print(output, end="", flush=True)


def _render_md_line(term: "Terminal", line: str, width: int) -> str:
    """Simple markdown rendering for a single line.

    Padding is applied to the plain text *before* wrapping in ANSI
    color codes so that escape sequences don't shift the right border.
    """
    stripped = line.rstrip()

    # Headings — pad first, color second
    if stripped.startswith("# "):
        text = stripped[2:].strip()
        padded = text.center(width)[:width]
        return term.bold(term.bright_white(padded))
    if stripped.startswith("## "):
        text = stripped[3:].strip()
        padded = text[:width].ljust(width)
        return term.bold(term.bright_cyan(padded))
    if stripped.startswith("### "):
        text = stripped[4:].strip()
        padded = text[:width].ljust(width)
        return term.bold(padded)

    # Indented lines (code/shortcuts)
    if stripped.startswith("  "):
        padded = stripped[:width].ljust(width)
        return term.white(padded)

    # Empty line
    if not stripped:
        return " " * width

    # Normal text
    return stripped[:width].ljust(width)

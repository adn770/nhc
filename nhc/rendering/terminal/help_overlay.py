"""Scrollable help overlay that renders a markdown document."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nhc.i18n import current_lang

if TYPE_CHECKING:
    from blessed import Terminal

_DOCS_DIR = Path(__file__).parent.parent.parent.parent / "docs"


def _load_help() -> list[str]:
    """Load the help document for the active language, line by line."""
    lang = current_lang()
    path = _DOCS_DIR / f"help_{lang}.md"
    if not path.exists():
        path = _DOCS_DIR / "help_en.md"
    return path.read_text().splitlines()


def show_help(term: "Terminal") -> None:
    """Display a scrollable help overlay. Blocks until ESC/q/?."""
    lines = _load_help()
    scroll = 0
    # Reserve 2 lines for border + footer
    view_h = term.height - 4
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


def _draw(
    term: "Terminal", lines: list[str], scroll: int, view_h: int,
) -> None:
    """Render the help overlay as a centered box."""
    box_w = min(72, term.width - 4)
    box_x = (term.width - box_w) // 2
    box_y = 1
    inner_w = box_w - 4  # 2 border + 2 padding

    output = ""

    # Top border
    output += term.move_xy(box_x, box_y)
    output += "╭" + "─" * (box_w - 2) + "╮"

    # Content lines
    visible = lines[scroll:scroll + view_h]
    for i in range(view_h):
        y = box_y + 1 + i
        if i < len(visible):
            raw = visible[i]
            rendered = _render_md_line(term, raw, inner_w)
        else:
            rendered = " " * inner_w
        output += term.move_xy(box_x, y)
        output += "│ " + rendered + " │"

    # Scroll indicator
    total = len(lines)
    if total > view_h:
        pct = int(100 * scroll / max(1, total - view_h))
        indicator = f" {scroll + 1}-{min(scroll + view_h, total)}/{total}"
        indicator += f" ({pct}%)"
    else:
        indicator = ""

    # Bottom border with footer
    footer_line = "  ESC/q: close  ↑↓: scroll  PgUp/PgDn: page"
    footer_line += indicator
    bot_y = box_y + 1 + view_h
    output += term.move_xy(box_x, bot_y)
    output += "├" + "─" * (box_w - 2) + "┤"
    output += term.move_xy(box_x, bot_y + 1)
    footer_padded = footer_line[:inner_w].ljust(inner_w)
    output += "│ " + term.bright_black(footer_padded) + " │"
    output += term.move_xy(box_x, bot_y + 2)
    output += "╰" + "─" * (box_w - 2) + "╯"

    print(output, end="", flush=True)


def _render_md_line(term: "Terminal", line: str, width: int) -> str:
    """Simple markdown rendering for a single line."""
    stripped = line.rstrip()

    # Headings
    if stripped.startswith("# "):
        text = stripped[2:].strip()
        return term.bold(term.bright_white(text.center(width)))[:width + 20]
    if stripped.startswith("## "):
        text = stripped[3:].strip()
        return term.bold(term.bright_cyan(text))[:width + 20].ljust(width + 20)[:width + 20]
    if stripped.startswith("### "):
        text = stripped[4:].strip()
        return term.bold(text)[:width + 20].ljust(width + 20)[:width + 20]

    # Indented lines (code/shortcuts) — keep as-is
    if stripped.startswith("  "):
        return term.white(stripped[:width].ljust(width))

    # Empty line
    if not stripped:
        return " " * width

    # Normal text
    return stripped[:width].ljust(width)

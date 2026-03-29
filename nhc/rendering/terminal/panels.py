"""Zone 2 (status lines) and Zone 3 (message log) rendering.

Layout:
  Zone 1: MAP (full width, top)
  ─────────────────────────────────────────────
  Zone 2: Status (3 lines)
    Line 1: 📍 Location │ ⬇ Depth │ ⏳ Turn │ ❤️ HP bar
    Line 2: 💪 STR │ 🏃 DEX │ 🛡️ CON │ 🧠 INT │ 👁️ WIS │ ✨ CHA │ ⚔️ Wpn │ 🛡️ AC
    Line 3: 🎒 Inventory items
  ─────────────────────────────────────────────
  Zone 3: Messages (4 lines, scrollable)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.i18n import t as tr

if TYPE_CHECKING:
    from blessed import Terminal


# ── Box-drawing characters (dynamic from theme) ─────────────────────
def _h_line():
    from nhc.rendering.terminal.themes import get_theme
    return get_theme().h_line

def _sep():
    from nhc.rendering.terminal.themes import get_theme
    return get_theme().v_sep


def render_status(
    term: "Terminal",
    y: int,
    width: int,
    stats: dict,
    items: list[str],
    max_slots: int,
    total_slots_used: int = 0,
) -> str:
    """Render the 3-line status zone (Zone 2).

    Returns positioned terminal output string.
    """
    output = ""

    # ── Separator above status ──
    output += term.move_xy(0, y) + term.bright_black(_h_line() * width)

    # ── Line 1: Location, Depth, Turn, HP ──
    level_name = stats.get("level_name", "???")
    depth = stats.get("depth", 1)
    turn = stats.get("turn", 0)
    hp = stats.get("hp", 0)
    hp_max = stats.get("hp_max", 1)
    hp_pct = hp / hp_max if hp_max > 0 else 0

    if hp_pct > 0.5:
        hp_color = term.bright_green
    elif hp_pct > 0.25:
        hp_color = term.bright_yellow
    else:
        hp_color = term.bright_red

    bar_w = 12
    filled = max(0, int(bar_w * hp_pct))
    bar = hp_color("█" * filled) + term.bright_black("░" * (bar_w - filled))

    plevel = stats.get("plevel", 1)
    xp = stats.get("xp", 0)
    xp_next = stats.get("xp_next", 20)

    gold = stats.get("gold", 0)

    line1 = (
        f" 📍 {term.bold(level_name)}"
        f"{_sep()}⬇ {tr('ui.depth')} {depth}"
        f"{_sep()}⏳ {tr('ui.turn')} {turn}"
        f"{_sep()}Lv {plevel} ({xp}/{xp_next} XP)"
        f"{_sep()}💰 {term.bright_yellow(str(gold))}"
        f"{_sep()}❤️  {bar} {hp_color(str(hp))}/{hp_max}"
    )
    output += term.move_xy(0, y + 1) + _pad(line1, width)

    # ── Line 2: Name, Stats, Equipment ──
    s = stats
    weapon = s.get("weapon", "unarmed")
    armor_def = s.get("armor_def", 10 + s.get("dex", 0))
    char_name = s.get("char_name", "")
    char_bg = s.get("char_background", "")
    identity = f" {term.bold(char_name)}"
    if char_bg:
        identity += f" ({char_bg})"

    # Build equipment summary for after stats
    equip_parts = [f"⚔️  {weapon}"]
    armor_name = s.get("armor_name", "")
    shield_name = s.get("shield_name", "")
    helmet_name = s.get("helmet_name", "")
    if armor_name:
        equip_parts.append(armor_name)
    if shield_name:
        equip_parts.append(shield_name)
    if helmet_name:
        equip_parts.append(helmet_name)
    equip_parts.append(f"AC {armor_def}")

    line2 = (
        f"{identity}"
        f"{_sep()}{tr('stats.str')}:{s.get('str', 0):+d}"
        f" {tr('stats.dex')}:{s.get('dex', 0):+d}"
        f" {tr('stats.con')}:{s.get('con', 0):+d}"
        f" {tr('stats.int')}:{s.get('int', 0):+d}"
        f" {tr('stats.wis')}:{s.get('wis', 0):+d}"
        f" {tr('stats.cha')}:{s.get('cha', 0):+d}"
        f"{_sep()}" + _sep().join(equip_parts)
    )
    output += term.move_xy(0, y + 2) + _pad(line2, width)

    # ── Line 3: Inventory ──
    # total_slots_used includes equipped items (Knave: all gear uses slots)
    used = total_slots_used if total_slots_used else len(items)
    if not items:
        inv_detail = term.bright_black(tr("ui.empty"))
    else:
        inv_detail = term.white(" · ".join(items))

    line3 = f" 🎒 {used}/{max_slots}  {inv_detail}"
    output += term.move_xy(0, y + 3) + _pad(line3, width)

    return output


def render_messages(
    term: "Terminal",
    y: int,
    width: int,
    height: int,
    messages: list[str],
    scroll_offset: int = 0,
) -> str:
    """Render the scrollable message log (Zone 3).

    Args:
        scroll_offset: How many lines scrolled back from newest (0 = latest).
    """
    output = ""

    # ── Separator above messages ──
    scroll_hint = ""
    total = len(messages)
    if scroll_offset > 0:
        scroll_hint = f" ↑↓ {tr('ui.scroll_hint')} ({total - scroll_offset}-{total})"
    sep_line = _h_line() * (width - len(scroll_hint)) + scroll_hint
    output += term.move_xy(0, y) + term.bright_black(sep_line)

    # Slice the visible window
    if total == 0:
        visible: list[str] = []
    else:
        end = total - scroll_offset
        start = max(0, end - height)
        visible = messages[start:end]

    for i in range(height):
        if i < len(visible):
            msg = visible[i]
            output += term.move_xy(0, y + 1 + i) + f" {msg}"[:width].ljust(width)
        else:
            output += term.move_xy(0, y + 1 + i) + " " * width

    return output


def _pad(line: str, width: int) -> str:
    """Pad a line to fill width. Handles ANSI escape sequences in length."""
    # We can't simply truncate because of escape codes;
    # ljust with a generous width is safe since terminal clips anyway
    return line + " " * max(0, width)

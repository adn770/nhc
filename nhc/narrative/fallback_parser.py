"""Keyword-based intent parser for typed mode without an LLM.

When running with ``--provider none --mode typed``, this parser
extracts actions from natural-language text using simple pattern
matching.  It handles common roguelike intents in English, Catalan,
and Spanish.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level

# Direction keywords → (dx, dy)
_DIRECTIONS: dict[str, tuple[int, int]] = {
    # English
    "north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0),
    "northeast": (1, -1), "northwest": (-1, -1),
    "southeast": (1, 1), "southwest": (-1, 1),
    "up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0),
    "n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0),
    "ne": (1, -1), "nw": (-1, -1), "se": (1, 1), "sw": (-1, 1),
    # Catalan
    "nord": (0, -1), "sud": (0, 1), "est": (1, 0), "oest": (-1, 0),
    "amunt": (0, -1), "avall": (0, 1), "esquerra": (-1, 0), "dreta": (1, 0),
    # Spanish
    "norte": (0, -1), "sur": (0, 1), "este": (1, 0), "oeste": (-1, 0),
    "arriba": (0, -1), "abajo": (0, 1), "izquierda": (-1, 0), "derecha": (1, 0),
}

# Attack keywords
_ATTACK_WORDS = {
    "attack", "hit", "strike", "fight", "kill", "slay",
    "ataca", "colpeja", "lluita", "mata",  # Catalan
    "ataca", "golpea", "lucha", "mata",    # Spanish
}

# Pickup keywords
_PICKUP_WORDS = {
    "pick", "grab", "take", "get", "loot", "collect",
    "agafa", "recull", "pren",      # Catalan
    "coge", "recoge", "toma",       # Spanish
}

# Wait keywords
_WAIT_WORDS = {
    "wait", "rest", "pass", "stay",
    "espera", "descansa",            # Catalan
    "espera", "descansa",            # Spanish
}

# Look keywords
_LOOK_WORDS = {
    "look", "examine", "inspect", "search", "observe",
    "mira", "examina", "inspecciona", "escorcolla",  # Catalan
    "mira", "examina", "inspecciona", "registra",    # Spanish
}

# Descend keywords
_DESCEND_WORDS = {
    "descend", "stairs", "go down", "climb down",
    "descendeix", "escales", "baixa",              # Catalan
    "desciende", "escaleras", "baja",              # Spanish
}

# Use/drink/read keywords
_USE_WORDS = {
    "use", "drink", "quaff", "read", "cast",
    "usa", "beu", "llegeix", "llança",  # Catalan
    "usa", "bebe", "lee", "lanza",      # Spanish
}


def parse_intent_keywords(
    text: str,
    world: "World",
    level: "Level",
    player_id: int,
) -> list[dict[str, Any]]:
    """Parse typed text into action dicts using keyword matching.

    Returns a list of action dicts in the same format as the LLM
    parser, so they can be fed to ``action_plan_to_actions()``.
    """
    text_lower = text.lower().strip()
    words = text_lower.split()

    if not words:
        return [{"action": "wait"}]

    # Check non-movement intents FIRST (they may contain direction words
    # like "up" in "pick up" or "down" in "go down the stairs")

    # Attack
    if any(w in _ATTACK_WORDS for w in words):
        target = _find_nearest_creature(world, level, player_id)
        if target is not None:
            return [{"action": "attack", "target": target}]

    # Pickup
    if any(w in _PICKUP_WORDS for w in words):
        item = _find_item_at_player(world, player_id)
        if item is not None:
            return [{"action": "pickup", "item": item}]

    # Descend
    if any(w in _DESCEND_WORDS for w in words):
        return [{"action": "descend"}]

    # Look
    if any(w in _LOOK_WORDS for w in words):
        return [{"action": "look", "target": "around"}]

    # Wait
    if any(w in _WAIT_WORDS for w in words):
        return [{"action": "wait"}]

    # Use item (try to match item name in inventory)
    if any(w in _USE_WORDS for w in words):
        item = _find_inventory_item_by_name(world, player_id, text_lower)
        if item is not None:
            return [{"action": "use_item", "item": item}]

    # Direction-only movement (checked LAST to avoid false matches
    # on "pick up", "go down the stairs", etc.)
    for word in words:
        if word in _DIRECTIONS:
            dx, dy = _DIRECTIONS[word]
            return [{"action": "move", "direction": _direction_name(dx, dy)}]

    # "go <direction>" (only if no other intent matched above)
    if words[0] in ("go", "move", "walk", "run",
                     "anar", "mou", "camina", "corre",
                     "ir", "mover", "caminar", "correr"):
        for word in words[1:]:
            if word in _DIRECTIONS:
                dx, dy = _DIRECTIONS[word]
                return [{"action": "move",
                         "direction": _direction_name(dx, dy)}]

    # Default: treat as a wait
    return [{"action": "wait"}]


def _direction_name(dx: int, dy: int) -> str:
    """Convert (dx, dy) back to a direction name for the action plan."""
    return {
        (0, -1): "north", (0, 1): "south",
        (1, 0): "east", (-1, 0): "west",
        (1, -1): "ne", (-1, -1): "nw",
        (1, 1): "se", (-1, 1): "sw",
    }.get((dx, dy), "north")


def _find_nearest_creature(
    world: "World", level: "Level", player_id: int,
) -> int | None:
    """Find the nearest visible creature to the player."""
    pos = world.get_component(player_id, "Position")
    if not pos:
        return None

    best_dist = 999
    best_eid = None
    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if not tile or not tile.visible:
            continue
        dist = abs(cpos.x - pos.x) + abs(cpos.y - pos.y)
        if dist < best_dist:
            best_dist = dist
            best_eid = eid

    return best_eid


def _find_item_at_player(world: "World", player_id: int) -> int | None:
    """Find an item at the player's position."""
    pos = world.get_component(player_id, "Position")
    if not pos:
        return None

    for eid, _, ipos in world.query("Description", "Position"):
        if ipos is None or eid == player_id:
            continue
        if ipos.x == pos.x and ipos.y == pos.y:
            if (not world.has_component(eid, "AI")
                    and not world.has_component(eid, "Trap")):
                return eid
    return None


def _find_inventory_item_by_name(
    world: "World", player_id: int, text: str,
) -> int | None:
    """Find an inventory item whose name appears in the text."""
    inv = world.get_component(player_id, "Inventory")
    if not inv:
        return None

    for item_id in inv.slots:
        desc = world.get_component(item_id, "Description")
        if desc and desc.name.lower() in text:
            return item_id
    return None

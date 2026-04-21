"""Teleporter-pad movement hook.

Called by the game loop after every resolved action. If the player
is standing on a tile with feature ``teleporter_pad`` and the level
carries a matching entry in ``teleporter_pairs``, move the player
to the paired tile. One hop only — landing on another pad at the
destination does not chain.

Stamping pads + pairs is the mage-residence assemblers' job; this
helper only implements the transit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.i18n import t

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level


TELEPORTER_FEATURE = "teleporter_pad"


def maybe_teleport_player(
    world: "World", level: "Level", player_id: int,
) -> bool:
    """Move the player off a teleporter pad to its paired tile.

    Returns ``True`` when a teleport happened, ``False`` otherwise.
    No-op when the player is off a pad, when the level has no
    ``teleporter_pairs`` map, or when the entry under the player
    has no registered pair.
    """
    pos = world.get_component(player_id, "Position")
    if pos is None:
        return False
    tile = level.tile_at(pos.x, pos.y)
    if tile is None or tile.feature != TELEPORTER_FEATURE:
        return False
    pairs = getattr(level, "teleporter_pairs", None)
    if not pairs:
        return False
    target = pairs.get((pos.x, pos.y))
    if target is None:
        return False
    pos.x, pos.y = target
    return True


def teleport_message() -> str:
    return t("teleporter.step")

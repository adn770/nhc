"""Loot generation from creature LootTable components."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from nhc.entities.components import LootTable, Position
from nhc.entities.registry import EntityRegistry
from nhc.utils.rng import get_rng, roll_dice

if TYPE_CHECKING:
    from nhc.core.ecs import World


def generate_loot(
    world: "World",
    loot_table: LootTable,
    x: int,
    y: int,
    level_id: str = "",
) -> list[int]:
    """Generate loot items from a LootTable and place them on the map.

    Each entry in the table is (item_id, probability[, dice_for_quantity]).
    Returns list of created entity IDs.
    """
    rng = get_rng()
    spawned: list[int] = []

    for entry in loot_table.entries:
        item_id = entry[0]
        probability = entry[1]

        if rng.random() > probability:
            continue

        try:
            components = EntityRegistry.get_item(item_id)
        except KeyError:
            continue

        # Handle quantity dice (e.g. "2d6" gold)
        if len(entry) >= 3 and entry[2]:
            quantity = roll_dice(entry[2], rng)
            desc = components.get("Description")
            if desc:
                desc.name = f"{quantity} {desc.name}"

        components["Position"] = Position(x=x, y=y, level_id=level_id)
        eid = world.create_entity(components)
        spawned.append(eid)

    return spawned

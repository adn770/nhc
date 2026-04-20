"""Spawn a sub-hex family site's population into the ECS world.

The sub-hex family generators emit a :class:`SubHexSite` with a
:class:`SubHexPopulation` describing the creatures, NPCs, items,
and feature tile tags the site wants to stamp onto the world. This
module walks those lists and creates the matching ECS entities
with a :class:`Position` tied to the site's Level id so the
overland / site boundary stays clean.

Used by :meth:`Game.enter_sub_hex_family_site` on cache miss (on a
cache hit, the entities are still alive in the ECS world, so
spawning again would duplicate them).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nhc.entities.components import BlocksMovement, Position
from nhc.entities.registry import EntityRegistry

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.hexcrawl.sub_hex_sites import SubHexSite

logger = logging.getLogger(__name__)


def populate_sub_hex_site(
    world: "World", site: "SubHexSite",
) -> list[int]:
    """Spawn ``site.population`` into ``world``; return new entity ids.

    Creatures and NPCs go through ``EntityRegistry.get_creature``
    (the NPC side of the registry lives under the creature factory
    today — innkeepers, adventurers — so keeping them on one lookup
    avoids a parallel NPC factory table). Items go through
    ``get_item``. Feature tile tags are ignored here; generators are
    responsible for stamping them onto the Level directly.
    """
    level = site.level
    spawned: list[int] = []
    population = site.population

    for entity_id, (x, y) in (
        list(population.creatures) + list(population.npcs)
    ):
        try:
            components = EntityRegistry.get_creature(entity_id)
        except KeyError:
            logger.warning(
                "Unknown creature/npc in sub-hex population: %s",
                entity_id,
            )
            continue
        components["BlocksMovement"] = BlocksMovement()
        components["Position"] = Position(
            x=x, y=y, level_id=level.id,
        )
        spawned.append(world.create_entity(components))

    for entity_id, (x, y) in population.items:
        try:
            components = EntityRegistry.get_item(entity_id)
        except KeyError:
            logger.warning(
                "Unknown item in sub-hex population: %s",
                entity_id,
            )
            continue
        components["Position"] = Position(
            x=x, y=y, level_id=level.id,
        )
        spawned.append(world.create_entity(components))

    for entity_id, (x, y) in population.features:
        try:
            components = EntityRegistry.get_feature(entity_id)
        except KeyError:
            logger.warning(
                "Unknown feature entity in sub-hex population: %s",
                entity_id,
            )
            continue
        components["Position"] = Position(
            x=x, y=y, level_id=level.id,
        )
        spawned.append(world.create_entity(components))

    return spawned

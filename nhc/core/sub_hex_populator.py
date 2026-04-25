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
    from nhc.sites._types import SubHexSite

logger = logging.getLogger(__name__)


def _stable_id(entity_id: str, x: int, y: int) -> str:
    """Stable per-placement key: registry id + tile coord.

    Used by the C3 mutation-replay path to recognise "this is the
    same placement we spawned last visit," so killed creatures and
    looted items don't re-spawn."""
    return f"{entity_id}_{x}_{y}"


def populate_sub_hex_site(
    world: "World",
    site: "SubHexSite",
    *,
    mutations: dict | None = None,
) -> list[int]:
    """Spawn ``site.population`` into ``world``; return new entity ids.

    Creatures and NPCs go through ``EntityRegistry.get_creature``
    (the NPC side of the registry lives under the creature factory
    today — innkeepers, adventurers — so keeping them on one lookup
    avoids a parallel NPC factory table). Items go through
    ``get_item``. Feature tile tags are ignored here; generators are
    responsible for stamping them onto the Level directly.

    When ``mutations`` is passed, entries listed in
    ``mutations["killed"]`` (by stable id) and ``mutations["looted"]``
    (by [x, y] tile) are skipped so replayed state stays consistent
    with the player's last visit.
    """
    from nhc.entities.components import SubHexStableId

    level = site.level
    spawned: list[int] = []
    population = site.population
    muts = mutations or {}
    killed = set(muts.get("killed", []))
    looted = {tuple(xy) for xy in muts.get("looted", [])}

    for entity_id, (x, y) in (
        list(population.creatures) + list(population.npcs)
    ):
        sid = _stable_id(entity_id, x, y)
        if sid in killed:
            continue
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
        components["SubHexStableId"] = SubHexStableId(stable_id=sid)
        spawned.append(world.create_entity(components))

    for entity_id, (x, y) in population.items:
        if (x, y) in looted:
            continue
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
        components["SubHexStableId"] = SubHexStableId(
            stable_id=_stable_id(entity_id, x, y),
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
        components["SubHexStableId"] = SubHexStableId(
            stable_id=_stable_id(entity_id, x, y),
        )
        spawned.append(world.create_entity(components))

    return spawned

"""Site population system: spec → resolver → populator pipeline."""

from __future__ import annotations

import random

import pytest

from nhc.entities.registry import EntityRegistry
from nhc.sites._population import (
    Placement,
    PopulationEntry,
    SITE_POPULATION,
    populate_site_placements,
    resolve_site_population,
)
from nhc.sites._types import SiteTier
from nhc.sites.farm import assemble_farm


@pytest.fixture(scope="module", autouse=True)
def _bootstrap() -> None:
    EntityRegistry.discover_all()


def _make_world():
    from nhc.core.ecs import World
    return World()


# ---------------------------------------------------------------------------
# Spec table
# ---------------------------------------------------------------------------


def test_farm_tiny_spec_includes_farmer_and_farmhand() -> None:
    """TINY farm has the rumour-vendor farmer inside plus 1-2
    silent farmhands on the surface."""
    entries = SITE_POPULATION[("farm", SiteTier.TINY)]
    ids = [e.entity_id for e in entries]
    assert "farmer" in ids
    assert "farmhand" in ids
    farmer = next(e for e in entries if e.entity_id == "farmer")
    assert farmer.placement == "in_building_0"
    farmhand = next(e for e in entries if e.entity_id == "farmhand")
    assert farmhand.placement == "on_open_surface"


def test_farm_small_spec_scales_farmhand_count() -> None:
    """SMALL farm bumps the farmhand range vs TINY."""
    tiny_hands = next(
        e for e in SITE_POPULATION[("farm", SiteTier.TINY)]
        if e.entity_id == "farmhand"
    )
    small_hands = next(
        e for e in SITE_POPULATION[("farm", SiteTier.SMALL)]
        if e.entity_id == "farmhand"
    )
    assert small_hands.count_max > tiny_hands.count_max


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def test_resolve_tiny_farm_places_farmer_inside_and_farmhand_on_surface(
) -> None:
    """The resolver lands the farmer on the farmhouse interior
    level and the farmhand(s) on the surface level."""
    site = assemble_farm(
        "f1", random.Random(1), tier=SiteTier.TINY,
    )
    placements = resolve_site_population(
        site, "farm", SiteTier.TINY, random.Random(2),
    )
    by_entity: dict[str, list[Placement]] = {}
    for p in placements:
        by_entity.setdefault(p.entity_id, []).append(p)

    assert by_entity["farmer"], "expected at least one farmer"
    farmer = by_entity["farmer"][0]
    assert farmer.level_id == site.buildings[0].ground.id, (
        "farmer must land on the farmhouse interior, not the "
        "surface field"
    )

    assert by_entity.get("farmhand"), "expected at least one farmhand"
    for hand in by_entity["farmhand"]:
        assert hand.level_id == site.surface.id, (
            "farmhands belong on the surface, not inside the "
            "farmhouse"
        )


def test_resolve_unknown_kind_returns_empty() -> None:
    """Sites without a SITE_POPULATION entry get no placements;
    they keep their existing populator wiring (today most kinds)."""
    site = assemble_farm(
        "f1", random.Random(1), tier=SiteTier.TINY,
    )
    placements = resolve_site_population(
        site, "not_a_kind", SiteTier.TINY, random.Random(3),
    )
    assert placements == []


def test_resolve_skips_reserved_surface_tiles() -> None:
    """The reserved set excludes specific (x, y) coords from
    every surface placement (used by entry methods to keep the
    player's landing tile clear)."""
    site = assemble_farm(
        "f2", random.Random(7), tier=SiteTier.SMALL,
    )
    # Pick the first FLOOR tile and reserve it; subsequent
    # placements must avoid it.
    reserved: set[tuple[int, int]] = set()
    surface = site.surface
    for y in range(surface.height):
        for x in range(surface.width):
            tile = surface.tile_at(x, y)
            if tile and tile.terrain.name == "FLOOR":
                reserved.add((x, y))
                break
        if reserved:
            break
    placements = resolve_site_population(
        site, "farm", SiteTier.SMALL, random.Random(11),
        reserved=reserved,
    )
    surface_coords = {
        (p.x, p.y) for p in placements
        if p.level_id == site.surface.id
    }
    assert reserved.isdisjoint(surface_coords)


# ---------------------------------------------------------------------------
# Populator
# ---------------------------------------------------------------------------


def test_populate_creates_entities_with_stable_ids() -> None:
    """Each placement spawns one entity with a SubHexStableId
    keyed on the registry id + level_id + tile coord."""
    site = assemble_farm(
        "f3", random.Random(4), tier=SiteTier.TINY,
    )
    placements = resolve_site_population(
        site, "farm", SiteTier.TINY, random.Random(5),
    )
    world = _make_world()
    eids = populate_site_placements(world, placements)
    assert len(eids) == len(placements)
    for eid, p in zip(eids, placements):
        sid = world.get_component(eid, "SubHexStableId")
        assert sid is not None
        assert sid.stable_id == (
            f"{p.entity_id}_{p.level_id}_{p.x}_{p.y}"
        )
        pos = world.get_component(eid, "Position")
        assert (pos.x, pos.y, pos.level_id) == (
            p.x, p.y, p.level_id,
        )


def test_populate_skips_killed_entries_on_replay() -> None:
    """Mutation replay: a placement whose stable id is in
    ``mutations["killed"]`` must not respawn on cache miss, the
    same way the existing sub-hex populator handles it."""
    site = assemble_farm(
        "f4", random.Random(8), tier=SiteTier.TINY,
    )
    placements = resolve_site_population(
        site, "farm", SiteTier.TINY, random.Random(9),
    )
    farmer = next(p for p in placements if p.entity_id == "farmer")
    killed_sid = (
        f"{farmer.entity_id}_{farmer.level_id}_{farmer.x}"
        f"_{farmer.y}"
    )
    world = _make_world()
    eids = populate_site_placements(
        world, placements, mutations={"killed": [killed_sid]},
    )
    # The farmer must not spawn; everyone else does.
    assert len(eids) == len(placements) - 1
    for eid in eids:
        sid = world.get_component(eid, "SubHexStableId")
        assert sid.stable_id != killed_sid

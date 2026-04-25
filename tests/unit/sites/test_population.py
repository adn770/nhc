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


def test_sacred_spec_uses_pilgrim_near_feature() -> None:
    """Sacred sites place an occasional pilgrim adjacent to the
    centerpiece (count_min=0 keeps it rare)."""
    entries = SITE_POPULATION[("sacred", SiteTier.SMALL)]
    assert len(entries) == 1
    pilgrim = entries[0]
    assert pilgrim.entity_id == "pilgrim"
    assert pilgrim.placement == "near_feature"
    assert pilgrim.count_min == 0


def test_wayside_spec_uses_campsite_traveller_near_feature() -> None:
    """Waysides bring a campsite_traveller across so wells +
    signposts double as roadside rumour stops."""
    entries = SITE_POPULATION[("wayside", SiteTier.SMALL)]
    assert any(
        e.entity_id == "campsite_traveller"
        and e.placement == "near_feature"
        for e in entries
    )


def test_resolve_near_feature_lands_orthogonal_to_feature_tile(
) -> None:
    """The ``near_feature`` strategy places the entity on a tile
    orthogonal to ``feature_tile`` (Manhattan distance 1)."""
    site = assemble_farm(
        "f5", random.Random(13), tier=SiteTier.TINY,
    )
    # Borrow the farm site as a generic Site fixture; the
    # near_feature strategy doesn't care about kind, just about
    # the surface having a free tile next to the feature.
    feature_tile = (
        site.surface.width // 2, site.surface.height // 2,
    )
    spec = [
        PopulationEntry("pilgrim", "near_feature", 1, 1),
    ]
    SITE_POPULATION[("farm", SiteTier.MEDIUM)] = spec
    try:
        placements = resolve_site_population(
            site, "farm", SiteTier.MEDIUM, random.Random(17),
            feature_tile=feature_tile,
        )
    finally:
        del SITE_POPULATION[("farm", SiteTier.MEDIUM)]
    if not placements:
        pytest.skip(
            "all four orthogonal neighbours blocked in this seed"
        )
    p = placements[0]
    dist = abs(p.x - feature_tile[0]) + abs(p.y - feature_tile[1])
    assert dist == 1


def test_mansion_spec_has_noble_and_servant() -> None:
    """A mansion places one noble inside buildings[0] (main hall)
    plus an occasional villager (servant) on the garden surface."""
    entries = SITE_POPULATION[("mansion", SiteTier.MEDIUM)]
    placements = {e.entity_id: e for e in entries}
    assert placements["noble"].placement == "in_building_0"
    assert placements["noble"].count_min == 1
    assert placements["villager"].placement == "on_open_surface"
    assert placements["villager"].count_min == 0


def test_tower_spec_has_resident_hermit() -> None:
    """A tower (mage variant or regular) keeps a single hermit /
    scholar on the ground floor."""
    entries = SITE_POPULATION[("tower", SiteTier.TINY)]
    assert len(entries) == 1
    assert entries[0].entity_id == "hermit"
    assert entries[0].placement == "in_building_0"
    assert entries[0].count_min == 1


def test_resolve_mansion_lands_noble_inside_first_building() -> None:
    """The mansion noble lands on the first building's ground
    floor, not on the surrounding garden surface."""
    from nhc.sites._site import assemble_site
    site = assemble_site(
        "mansion", "m1", random.Random(31),
    )
    placements = resolve_site_population(
        site, "mansion", SiteTier.MEDIUM, random.Random(33),
    )
    nobles = [p for p in placements if p.entity_id == "noble"]
    assert nobles, "expected at least one noble"
    assert nobles[0].level_id == site.buildings[0].ground.id


def test_resolve_tower_lands_hermit_inside_tower() -> None:
    """The tower hermit lands on the tower's ground floor (= the
    first building's ground level for the single-building site)."""
    from nhc.sites._site import assemble_site
    site = assemble_site(
        "tower", "t1", random.Random(41),
    )
    placements = resolve_site_population(
        site, "tower", SiteTier.TINY, random.Random(43),
    )
    hermits = [p for p in placements if p.entity_id == "hermit"]
    assert hermits, "expected at least one hermit"
    assert hermits[0].level_id == site.buildings[0].ground.id


def test_resolve_near_feature_skips_when_no_feature_tile() -> None:
    """``near_feature`` without ``feature_tile`` is a silent
    skip — generators that don't carry a centerpiece (clearings
    with no entity tag) shouldn't crash the resolver."""
    site = assemble_farm(
        "f6", random.Random(19), tier=SiteTier.TINY,
    )
    SITE_POPULATION[("farm", SiteTier.HUGE)] = [
        PopulationEntry("pilgrim", "near_feature", 1, 1),
    ]
    try:
        placements = resolve_site_population(
            site, "farm", SiteTier.HUGE, random.Random(23),
            feature_tile=None,
        )
    finally:
        del SITE_POPULATION[("farm", SiteTier.HUGE)]
    assert placements == []


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

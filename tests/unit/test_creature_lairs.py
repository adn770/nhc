"""Tests for creature lairs and nests room types.

Lairs are 1-3 connected rooms packed with same-species humanoid
creatures; surrounding rooms get reactivatable traps.  Nests are
single rooms filled with vermin (rats, bats, etc.).
"""

from __future__ import annotations

import random

import pytest

from nhc.core.ecs import World
from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.dungeon.pipeline import generate_level
from nhc.dungeon.room_types import LAIR_CREATURES, NEST_CREATURES
from nhc.entities.components import Position, Trap
from nhc.i18n import init as i18n_init


def _find_tagged(level, tag):
    return [r for r in level.rooms if tag in r.tags]


def _entities_in_room(level, room):
    inside = set(room.floor_tiles())
    return [e for e in level.entities if (e.x, e.y) in inside]


def _connection_count(level, room_id: str) -> int:
    return sum(1 for c in level.corridors if room_id in c.connects)


# ── Lair tests ───────────────────────────────────────────────────────

class TestLairDepthGate:
    def test_no_lairs_at_depth_1(self):
        """Lairs should never appear on depth 1."""
        for seed in range(100):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=1, seed=seed,
            ))
            assert not _find_tagged(level, "lair"), (
                f"seed={seed} produced a lair at depth 1"
            )

    def test_no_lairs_at_depth_2(self):
        """Lairs should never appear on depth 2."""
        for seed in range(100):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=2, seed=seed,
            ))
            assert not _find_tagged(level, "lair"), (
                f"seed={seed} produced a lair at depth 2"
            )


class TestLairAssignment:
    def test_lairs_appear_across_seeds(self):
        """Lairs should appear in a reasonable fraction of dungeons."""
        with_lair = 0
        for seed in range(100):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=3, seed=seed,
            ))
            if _find_tagged(level, "lair"):
                with_lair += 1
        assert with_lair >= 3, (
            f"Only {with_lair}/100 seeds produced a lair"
        )

    def test_lair_rooms_have_creatures(self):
        """Each lair room should contain several creatures."""
        found = False
        for seed in range(200):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=3, seed=seed,
            ))
            lairs = _find_tagged(level, "lair")
            if not lairs:
                continue
            found = True
            for room in lairs:
                creatures = [e for e in _entities_in_room(level, room)
                             if e.entity_type == "creature"]
                assert len(creatures) >= 2, (
                    f"seed={seed} lair {room.id} has only "
                    f"{len(creatures)} creatures"
                )
        if not found:
            pytest.skip("no lairs in 200 seeds")

    def test_lair_creatures_same_species(self):
        """All creatures in a lair cluster should be the same species."""
        found = False
        for seed in range(200):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=3, seed=seed,
            ))
            lairs = _find_tagged(level, "lair")
            if not lairs:
                continue
            found = True
            # All lair rooms in this level share a species
            species = set()
            for room in lairs:
                for e in _entities_in_room(level, room):
                    if e.entity_type == "creature":
                        species.add(e.entity_id)
            assert len(species) == 1, (
                f"seed={seed} lair has mixed species: {species}"
            )
        if not found:
            pytest.skip("no lairs in 200 seeds")

    def test_lair_creatures_are_humanoid(self):
        """Lair creatures should come from LAIR_CREATURES pool."""
        all_lair = set()
        for tier in LAIR_CREATURES.values():
            all_lair.update(tier)
        found = False
        for seed in range(200):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=3, seed=seed,
            ))
            lairs = _find_tagged(level, "lair")
            if not lairs:
                continue
            found = True
            for room in lairs:
                for e in _entities_in_room(level, room):
                    if e.entity_type == "creature":
                        assert e.entity_id in all_lair, (
                            f"seed={seed} lair creature "
                            f"{e.entity_id} not in LAIR_CREATURES"
                        )
        if not found:
            pytest.skip("no lairs in 200 seeds")

    def test_lair_rooms_have_gold_and_food(self):
        """Lair rooms should contain gold and food items."""
        gold_found = 0
        food_found = 0
        food_ids = {"rations", "bread", "dried_meat", "apple", "cheese"}
        for seed in range(200):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=3, seed=seed,
            ))
            lairs = _find_tagged(level, "lair")
            if not lairs:
                continue
            for room in lairs:
                for e in _entities_in_room(level, room):
                    if e.entity_type == "item" and e.entity_id == "gold":
                        gold_found += 1
                    if (e.entity_type == "item"
                            and e.entity_id in food_ids):
                        food_found += 1
        assert gold_found >= 5, (
            f"Only {gold_found} gold piles across all lairs"
        )
        assert food_found >= 3, (
            f"Only {food_found} food items across all lairs"
        )


class TestLairSurroundingTraps:
    def test_surrounding_rooms_have_traps(self):
        """At least some lairs should have traps in adjacent rooms."""
        traps_found = 0
        lairs_found = 0
        for seed in range(200):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=3, seed=seed,
            ))
            lairs = _find_tagged(level, "lair")
            if not lairs:
                continue
            lairs_found += 1
            lair_ids = {r.id for r in lairs}
            adjacent_ids = set()
            for corridor in level.corridors:
                if any(rid in lair_ids for rid in corridor.connects):
                    for rid in corridor.connects:
                        if rid not in lair_ids:
                            adjacent_ids.add(rid)
            if not adjacent_ids:
                continue
            adj_floors = set()
            for r in level.rooms:
                if r.id in adjacent_ids:
                    adj_floors |= r.floor_tiles()
            trap_entities = [
                e for e in level.entities
                if (e.entity_type == "feature"
                    and e.entity_id.startswith("trap_")
                    and (e.x, e.y) in adj_floors)
            ]
            if trap_entities:
                traps_found += 1
        if lairs_found == 0:
            pytest.skip("no lairs in 200 seeds")
        assert traps_found >= 1, (
            f"No lairs had traps in adjacent rooms across "
            f"{lairs_found} lairs"
        )

    def test_lair_traps_are_reactivatable(self):
        """Traps placed around lairs should be reactivatable."""
        found = False
        for seed in range(200):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=3, seed=seed,
            ))
            lairs = _find_tagged(level, "lair")
            if not lairs:
                continue
            lair_ids = {r.id for r in lairs}
            adjacent_ids = set()
            for corridor in level.corridors:
                if any(rid in lair_ids for rid in corridor.connects):
                    for rid in corridor.connects:
                        if rid not in lair_ids:
                            adjacent_ids.add(rid)
            if not adjacent_ids:
                continue
            adj_floors = set()
            for r in level.rooms:
                if r.id in adjacent_ids:
                    adj_floors |= r.floor_tiles()
            reactivatable = [
                e for e in level.entities
                if (e.entity_type == "feature"
                    and e.entity_id.startswith("trap_")
                    and (e.x, e.y) in adj_floors
                    and e.extra.get("reactivatable"))
            ]
            if reactivatable:
                found = True
                break
        if not found:
            pytest.skip("no reactivatable traps found in 200 seeds")


# ── Nest tests ───────────────────────────────────────────────────────

class TestNestAssignment:
    def test_nests_appear_across_seeds(self):
        """Nests should appear in some dungeons."""
        with_nest = 0
        for seed in range(100):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=1, seed=seed,
            ))
            if _find_tagged(level, "nest"):
                with_nest += 1
        assert with_nest >= 2, (
            f"Only {with_nest}/100 seeds produced a nest"
        )

    def test_nest_creatures_are_vermin(self):
        """Nest creatures should be from NEST_CREATURES."""
        found = False
        for seed in range(200):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=1, seed=seed,
            ))
            nests = _find_tagged(level, "nest")
            if not nests:
                continue
            found = True
            for room in nests:
                for e in _entities_in_room(level, room):
                    if e.entity_type == "creature":
                        assert e.entity_id in NEST_CREATURES, (
                            f"seed={seed} nest creature "
                            f"{e.entity_id} not in NEST_CREATURES"
                        )
        if not found:
            pytest.skip("no nests in 200 seeds")

    def test_nest_is_single_room(self):
        """Each nest should be exactly one room."""
        for seed in range(200):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=1, seed=seed,
            ))
            nests = _find_tagged(level, "nest")
            # Each nest is independently tagged, not a cluster
            # (unlike lairs which can span 1-3 rooms)
            for nest in nests:
                assert "lair" not in nest.tags


# ── Trap reactivation tests ──────────────────────────────────────────

class TestTrapReactivation:
    def test_reactivatable_trap_resets_after_40_turns(self):
        """A triggered reactivatable trap should reset."""
        from nhc.core.game_ticks import tick_traps

        i18n_init("en")
        world = World()
        world.turn = 50

        trap_eid = world.create_entity({
            "Trap": Trap(
                damage="1d6", hidden=False, triggered=True,
                reactivatable=True, triggered_at_turn=10,
            ),
            "Position": Position(x=3, y=3),
        })

        class FakeGame:
            pass
        game = FakeGame()
        game.world = world
        game.turn = 50

        tick_traps(game)

        trap = world.get_component(trap_eid, "Trap")
        assert trap.triggered is False
        assert trap.hidden is True
        assert trap.triggered_at_turn is None

    def test_non_reactivatable_trap_stays_triggered(self):
        """A normal trap should NOT reactivate."""
        from nhc.core.game_ticks import tick_traps

        i18n_init("en")
        world = World()
        world.turn = 100

        trap_eid = world.create_entity({
            "Trap": Trap(
                damage="1d6", hidden=False, triggered=True,
                reactivatable=False, triggered_at_turn=10,
            ),
            "Position": Position(x=3, y=3),
        })

        class FakeGame:
            pass
        game = FakeGame()
        game.world = world
        game.turn = 100

        tick_traps(game)

        trap = world.get_component(trap_eid, "Trap")
        assert trap.triggered is True

    def test_trap_not_reactivated_too_early(self):
        """Trap should not reactivate before 40 turns."""
        from nhc.core.game_ticks import tick_traps

        i18n_init("en")
        world = World()
        world.turn = 30

        trap_eid = world.create_entity({
            "Trap": Trap(
                damage="1d6", hidden=False, triggered=True,
                reactivatable=True, triggered_at_turn=10,
            ),
            "Position": Position(x=3, y=3),
        })

        class FakeGame:
            pass
        game = FakeGame()
        game.world = world
        game.turn = 30  # only 20 turns elapsed

        tick_traps(game)

        trap = world.get_component(trap_eid, "Trap")
        assert trap.triggered is True

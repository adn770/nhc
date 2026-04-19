"""Tests for vault room generation.

Vaults are tiny 2x2 or 3x2 rectangular rooms placed in void regions
with no corridor connections.  They are only reachable by digging
through walls and are filled with gold on every floor tile.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.bsp import BSPGenerator
from nhc.dungeon.model import EntityPlacement, SurfaceType, Terrain
from nhc.dungeon.pipeline import generate_level
from nhc.dungeon.populator import populate_level
from nhc.utils.rng import set_seed


def _find_vaults(level):
    return [r for r in level.rooms if "vault" in r.tags]


def _flood_floor(level, sx, sy):
    """Flood across FLOOR tiles starting at (sx, sy)."""
    visited: set[tuple[int, int]] = set()
    stack = [(sx, sy)]
    while stack:
        fx, fy = stack.pop()
        if (fx, fy) in visited:
            continue
        t = level.tile_at(fx, fy)
        if not t or t.terrain != Terrain.FLOOR:
            continue
        visited.add((fx, fy))
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            stack.append((fx + dx, fy + dy))
    return visited


class TestVaultGeneration:
    def test_vaults_present_across_seeds(self):
        """Across many seeds, vaults are generated at least sometimes.

        Vault placement is best-effort (depends on available void
        space) so we don't demand one per seed, but on a 120x40 map
        the vast majority of seeds should produce at least one.
        """
        with_vaults = 0
        total = 40
        for seed in range(total):
            set_seed(seed)
            gen = BSPGenerator()
            level = gen.generate(
                GenerationParams(width=120, height=40, depth=1),
                rng=random.Random(seed),
            )
            if _find_vaults(level):
                with_vaults += 1
        assert with_vaults >= total * 0.6, (
            f"Only {with_vaults}/{total} seeds produced vaults"
        )

    def test_vault_shape_is_2x2_or_3x2(self):
        for seed in range(20):
            set_seed(seed)
            gen = BSPGenerator()
            level = gen.generate(
                GenerationParams(width=120, height=40, depth=1),
                rng=random.Random(seed),
            )
            for v in _find_vaults(level):
                w, h = v.rect.width, v.rect.height
                assert (w, h) in {(2, 2), (3, 2), (2, 3)}, (
                    f"seed={seed} vault {v.id} is {w}x{h}"
                )

    def test_vault_tiles_are_floor(self):
        set_seed(777)
        gen = BSPGenerator()
        level = gen.generate(
            GenerationParams(width=120, height=40, depth=1),
            rng=random.Random(777),
        )
        vaults = _find_vaults(level)
        if not vaults:
            pytest.skip("no vaults on this seed")
        for v in vaults:
            for x, y in v.floor_tiles():
                tile = level.tile_at(x, y)
                assert tile is not None
                assert tile.terrain == Terrain.FLOOR, (
                    f"vault {v.id} tile ({x},{y}) is {tile.terrain}"
                )
                # Vault floor must never be flagged as a corridor
                assert tile.surface_type != SurfaceType.CORRIDOR

    def test_vault_perimeter_is_solid_wall(self):
        """Every tile adjacent (8-neighbor) to a vault floor that is
        not itself vault floor must be a WALL — no doors, no
        corridors, no VOID leaks that would let the player walk in."""
        for seed in range(30):
            set_seed(seed)
            gen = BSPGenerator()
            level = gen.generate(
                GenerationParams(width=120, height=40, depth=1),
                rng=random.Random(seed),
            )
            for v in _find_vaults(level):
                floor = v.floor_tiles()
                for fx, fy in floor:
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            if dx == 0 and dy == 0:
                                continue
                            p = (fx + dx, fy + dy)
                            if p in floor:
                                continue
                            t = level.tile_at(*p)
                            assert t is not None
                            assert t.terrain == Terrain.WALL, (
                                f"seed={seed} vault {v.id} leaks at "
                                f"{p}: terrain={t.terrain}"
                            )
                            assert t.feature is None, (
                                f"seed={seed} vault {v.id} has "
                                f"feature {t.feature} at {p}"
                            )

    def test_vault_unreachable_from_entry(self):
        for seed in range(30):
            set_seed(seed)
            gen = BSPGenerator()
            level = gen.generate(
                GenerationParams(width=120, height=40, depth=1),
                rng=random.Random(seed),
            )
            vaults = _find_vaults(level)
            if not vaults:
                continue
            entry = next(r for r in level.rooms if "entry" in r.tags)
            ex, ey = entry.rect.center
            reachable = _flood_floor(level, ex, ey)
            for v in vaults:
                for pos in v.floor_tiles():
                    assert pos not in reachable, (
                        f"seed={seed} vault {v.id} tile {pos} is "
                        f"reachable without digging"
                    )

    def test_normal_rooms_still_reachable_with_vaults(self):
        """Adding vaults must not break the all-non-vault-rooms-
        reachable invariant that the existing suite guards."""
        for seed in range(100):
            set_seed(seed)
            gen = BSPGenerator()
            level = gen.generate(
                GenerationParams(width=120, height=40, depth=1),
                rng=random.Random(seed),
            )
            entry = next(r for r in level.rooms if "entry" in r.tags)
            reachable = _flood_floor(level, *entry.rect.center)
            for room in level.rooms:
                if "vault" in room.tags:
                    continue
                rx, ry = room.rect.center
                assert (rx, ry) in reachable, (
                    f"seed={seed} non-vault {room.id} unreachable"
                )


class TestVaultPopulation:
    def test_populator_fills_every_vault_tile_with_gold(self):
        set_seed(42)
        level = generate_level(
            GenerationParams(width=120, height=40, depth=1, seed=42),
        )
        vaults = _find_vaults(level)
        if not vaults:
            pytest.skip("no vaults on this seed")
        for v in vaults:
            floor = v.floor_tiles()
            gold_positions = {
                (e.x, e.y) for e in level.entities
                if e.entity_type == "item" and e.entity_id == "gold"
            }
            missing = floor - gold_positions
            assert not missing, (
                f"vault {v.id} missing gold at {missing}"
            )

    def test_vaults_have_no_creatures_or_other_items(self):
        set_seed(1234)
        level = generate_level(
            GenerationParams(width=120, height=40, depth=1, seed=1234),
        )
        vaults = _find_vaults(level)
        if not vaults:
            pytest.skip("no vaults on this seed")
        vault_tiles: set[tuple[int, int]] = set()
        for v in vaults:
            vault_tiles |= v.floor_tiles()
        for e in level.entities:
            if (e.x, e.y) not in vault_tiles:
                continue
            assert e.entity_type == "item", (
                f"non-item entity {e.entity_id} placed in vault at "
                f"({e.x},{e.y})"
            )
            assert e.entity_id == "gold", (
                f"non-gold item {e.entity_id} placed in vault at "
                f"({e.x},{e.y})"
            )

    def test_vault_not_assigned_special_room_type(self):
        """room_types.assign_room_types must leave vault tags alone
        and must not overwrite vaults with standard/corridor/etc."""
        set_seed(42)
        level = generate_level(
            GenerationParams(width=120, height=40, depth=1, seed=42),
        )
        vaults = _find_vaults(level)
        if not vaults:
            pytest.skip("no vaults on this seed")
        for v in vaults:
            forbidden = {
                "standard", "corridor", "entry", "exit",
                "treasury", "armory", "library", "crypt",
                "shrine", "garden", "trap_room",
            }
            overlap = set(v.tags) & forbidden
            assert not overlap, (
                f"vault {v.id} has forbidden tags {overlap}"
            )

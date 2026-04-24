"""Building cross-floor stairs must follow physical semantics.

``<`` (``stairs_up``) takes the player to the floor physically
above. ``>`` (``stairs_down``) takes them to the floor physically
below or, on a ground floor with a descent link, down into the
subterranean dungeon. The engine used to swap the glyph
semantics so ``depth + 1`` always matched the descend action,
which produced two ``>`` symbols in the same room (one cross-
floor up-stair rendered as ``>``, one descent down-stair also
``>``) -- the bug reported from the live session.

The fix keeps the physical placement and lets the actions flip
direction for building floors so the floor cache still resolves.
These tests lock the invariants that user-visible glyphs follow
physical direction and that the action routing still works.
"""

from __future__ import annotations

import random

import pytest

from nhc.sites._site import assemble_site
from nhc.hexcrawl.model import DungeonRef


def _all_stair_tiles(building):
    rows = []
    for fi, floor in enumerate(building.floors):
        for y in range(floor.height):
            for x in range(floor.width):
                feat = floor.tiles[y][x].feature
                if feat in ("stairs_up", "stairs_down"):
                    rows.append((fi, x, y, feat))
    return rows


class TestBuildingCrossFloorGlyphs:
    def test_lower_floor_has_stairs_up(self):
        """On a tall tower the lower floor carries ``stairs_up``
        (``<``) because walking up a staircase physically reaches
        the floor above."""
        for seed in range(30):
            site = assemble_site(
                "tower", f"t_{seed}", random.Random(seed),
            )
            b = site.buildings[0]
            if len(b.floors) < 2:
                continue
            for link in b.stair_links:
                if isinstance(link.to_floor, DungeonRef):
                    continue
                lo = b.floors[link.from_floor]
                hi = b.floors[link.to_floor]
                lx, ly = link.from_tile
                ux, uy = link.to_tile
                assert lo.tiles[ly][lx].feature == "stairs_up", (
                    f"seed {seed}: lower floor cross-floor stair "
                    "must be stairs_up (<) -- physically walking "
                    "up reaches the upper floor"
                )
                assert hi.tiles[uy][ux].feature == "stairs_down", (
                    f"seed {seed}: upper floor cross-floor stair "
                    "must be stairs_down (>) -- physically walking "
                    "down reaches the lower floor"
                )
            break
        else:
            pytest.skip("no 2+ floor tower in 30 seeds")

    def test_ground_floor_descent_stays_stairs_down(self):
        """When a building has a descent into a dungeon, the
        descent tile on the ground floor must stay ``stairs_down``
        (``>``) -- that is the only direction to a cellar or
        crypt and matches the intent behind pressing ``>``."""
        for seed in range(30):
            site = assemble_site(
                "ruin", f"r_{seed}", random.Random(seed),
            )
            for b in site.buildings:
                descent_links = [
                    l for l in b.stair_links
                    if isinstance(l.to_floor, DungeonRef)
                ]
                for l in descent_links:
                    dx, dy = l.from_tile
                    assert b.ground.tiles[dy][dx].feature == (
                        "stairs_down"
                    ), (
                        f"seed {seed}: descent stair on ground "
                        "floor must be stairs_down"
                    )
                if descent_links:
                    return
        pytest.skip("no building with descent in 30 ruin seeds")

    def test_ground_floor_does_not_have_two_stairs_down(self):
        """The core of the reported bug: a building ground floor
        must not carry two ``stairs_down`` features. One is the
        descent; the other was the cross-floor stair to the upper
        floor -- wrongly flipped. After the fix the cross-floor
        stair is ``stairs_up`` so the room shows one ``<`` and
        one ``>``, visually distinguishable."""
        for seed in range(30):
            site = assemble_site(
                "tower", f"t_{seed}", random.Random(seed),
            )
            for b in site.buildings:
                if len(b.floors) < 2:
                    continue
                down_count = sum(
                    1 for y in range(b.ground.height)
                    for x in range(b.ground.width)
                    if b.ground.tiles[y][x].feature == "stairs_down"
                )
                assert down_count <= 1, (
                    f"seed {seed}, tower ground floor has "
                    f"{down_count} stairs_down tiles; at most one "
                    "is expected (the descent, if any)"
                )


class TestBuildingStairActionRouting:
    """The engine's stair actions must still find the right floor
    even though the glyphs now point at their physical meanings:
    pressing ``<`` on a building floor must route to the next
    higher floor index (which is cached at ``depth + 1``),
    pressing ``>`` must route to the next lower floor index
    (cached at ``depth - 1``), and ``>`` on a ground-floor
    descent tile must route through the dungeon descent
    pipeline."""

    @pytest.mark.asyncio
    async def test_ascend_from_building_ground_reaches_upper_floor(
        self, tmp_path,
    ):
        from nhc.core.actions import AscendStairsAction
        from nhc.core.events import LevelEntered
        from nhc.dungeon.model import Level, LevelMetadata, Terrain, Tile

        level = Level.create_empty("bld_f0", "ground", 1, 5, 5)
        level.metadata = LevelMetadata(theme="dungeon")
        level.building_id = "b0"
        level.floor_index = 0
        level.tiles[2][2] = Tile(
            terrain=Terrain.FLOOR, feature="stairs_up",
        )

        class _World:
            def get_component(self, eid, name):
                class _Pos:
                    x, y = 2, 2
                return _Pos()

        action = AscendStairsAction(actor=0)
        events = await action.execute(_World(), level)
        levels = [e for e in events if isinstance(e, LevelEntered)]
        assert len(levels) == 1
        assert levels[0].depth == level.depth + 1, (
            "ascending on a building floor must target the higher "
            "floor index (cached at depth + 1)"
        )

    @pytest.mark.asyncio
    async def test_descend_from_building_upper_floor_reaches_lower(
        self, tmp_path,
    ):
        from nhc.core.actions import DescendStairsAction
        from nhc.core.events import LevelEntered
        from nhc.dungeon.model import Level, LevelMetadata, Terrain, Tile

        level = Level.create_empty("bld_f1", "upper", 2, 5, 5)
        level.metadata = LevelMetadata(theme="dungeon")
        level.building_id = "b0"
        level.floor_index = 1
        level.tiles[2][2] = Tile(
            terrain=Terrain.FLOOR, feature="stairs_down",
        )

        class _World:
            def get_component(self, eid, name):
                class _Pos:
                    x, y = 2, 2
                return _Pos()

        action = DescendStairsAction(actor=0)
        events = await action.execute(_World(), level)
        levels = [e for e in events if isinstance(e, LevelEntered)]
        assert len(levels) == 1
        assert levels[0].depth == level.depth - 1, (
            "descending on a building upper floor must target the "
            "lower floor index (cached at depth - 1)"
        )

    @pytest.mark.asyncio
    async def test_descend_from_building_ground_targets_descent(
        self, tmp_path,
    ):
        """Ground floor ``stairs_down`` = descent to dungeon. The
        action emits ``LevelEntered(depth + 1)`` and the game's
        event handler routes that to ``_enter_building_descent``.
        This test just verifies the action's own output."""
        from nhc.core.actions import DescendStairsAction
        from nhc.core.events import LevelEntered
        from nhc.dungeon.model import Level, LevelMetadata, Terrain, Tile

        level = Level.create_empty("bld_f0", "ground", 1, 5, 5)
        level.metadata = LevelMetadata(theme="dungeon")
        level.building_id = "b0"
        level.floor_index = 0
        level.tiles[2][2] = Tile(
            terrain=Terrain.FLOOR, feature="stairs_down",
        )

        class _World:
            def get_component(self, eid, name):
                class _Pos:
                    x, y = 2, 2
                return _Pos()

        action = DescendStairsAction(actor=0)
        events = await action.execute(_World(), level)
        levels = [e for e in events if isinstance(e, LevelEntered)]
        assert len(levels) == 1
        assert levels[0].depth == level.depth + 1, (
            "descent stair on building ground floor must still "
            "emit depth + 1; game.py routes this to the descent "
            "pipeline"
        )

"""Cross-floor stair navigation for multi-building sites.

After item #1 (surface <-> building door crossing) a player can
walk from a mansion's building[0] ground floor through a shared
interior door onto building[1] ground floor. The follow-up here
is: when in building[1], DescendStairsAction on a stairs_down
tile (or AscendStairsAction on stairs_up) must resolve to
building[1]'s upper floor, not building[0]'s.

The engine hangs the depth-keyed floor cache off the first
building at site entry; swapping into a sibling must re-point
those cache slots at the sibling's ``Building.floors``.

These tests also confirm that every multi-floor building kind
ships the physical stair glyph convention: ``stairs_up`` on the
ground floor (``<``) and ``stairs_down`` on the floor above
(``>``). The stair actions internally swap depth direction for
building floors so the cache still resolves.
"""

from __future__ import annotations

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import DungeonRef, HexFeatureType
from nhc.i18n import init as i18n_init


class _FakeClient:
    game_mode = "classic"
    lang = "en"
    edge_doors = False
    messages: list[str] = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def _sync(*a, **kw):
            return None

        return _sync


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    i18n_init("en")
    EntityRegistry.discover_all()


def _make_game(tmp_path, mode: GameMode = GameMode.HEX_EASY) -> Game:
    from tests.unit.hexcrawl.test_enter_exit import _make_game as mk
    return mk(tmp_path, mode)


def _attach_mansion_site(g: Game, coord: HexCoord) -> None:
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.MANSION
    cell.dungeon = DungeonRef(
        template="procedural:mansion",
        depth=1,
        site_kind="mansion",
    )
    g.hex_player_position = coord


class TestBuildingGroundFloorStairGlyphs:
    def test_mansion_floor0_has_stairs_up(self):
        """Mansion ground floor exposes ``stairs_up`` (``<``) on
        its cross-floor stair because walking up physically
        reaches the floor above. The action maps this to
        ``depth + 1`` for the cache."""
        import random

        from nhc.dungeon.sites.mansion import assemble_mansion
        for seed in range(30):
            site = assemble_mansion("m1", random.Random(seed))
            for b in site.buildings:
                if len(b.floors) < 2:
                    continue
                features = [
                    t.feature for row in b.ground.tiles
                    for t in row
                    if t.feature in ("stairs_up", "stairs_down")
                ]
                assert "stairs_up" in features
                return
        pytest.skip("no multi-floor mansion in 30 seeds")

    def test_farm_floor0_has_stairs_up(self):
        import random

        from nhc.dungeon.sites.farm import assemble_farm
        for seed in range(50):
            site = assemble_farm("f1", random.Random(seed))
            for b in site.buildings:
                if len(b.floors) < 2:
                    continue
                features = [
                    t.feature for row in b.ground.tiles
                    for t in row
                    if t.feature in ("stairs_up", "stairs_down")
                ]
                assert "stairs_up" in features
                return
        pytest.skip("no multi-floor farm in 50 seeds")

    def test_keep_floor0_has_stairs_up(self):
        import random

        from nhc.dungeon.sites.keep import assemble_keep
        for seed in range(30):
            site = assemble_keep("k1", random.Random(seed))
            for b in site.buildings:
                if len(b.floors) < 2:
                    continue
                features = [
                    t.feature for row in b.ground.tiles
                    for t in row
                    if t.feature in ("stairs_up", "stairs_down")
                ]
                assert "stairs_up" in features
                return
        pytest.skip("no multi-floor keep in 30 seeds")


@pytest.mark.asyncio
async def test_mansion_sibling_activates_on_swap(tmp_path) -> None:
    """After swapping into a sibling building via the interior
    door, the depth-keyed floor cache points at that building's
    floors, not the first building's."""
    g = _make_game(tmp_path)
    _attach_mansion_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    site = g._active_site
    if not site.interior_doors or len(site.buildings) < 2:
        pytest.skip("mansion seed produced no interior doors")
    # Find an interior door leading to any sibling building.
    (fid, fx, fy), (tid, tx, ty) = next(
        iter(site.interior_doors.items())
    )
    source = next(b for b in site.buildings if b.id == fid)
    target = next(b for b in site.buildings if b.id == tid)
    g.level = source.ground
    g.level.tiles[fy][fx].feature = "door_open"
    pos = g.world.get_component(g.player_id, "Position")
    pos.x, pos.y = fx, fy
    pos.level_id = g.level.id
    # Traversal now requires the move direction to match the
    # door's side (cross through the wall edge).
    _side_to_dir = {
        "north": (0, -1), "south": (0, 1),
        "east": (1, 0), "west": (-1, 0),
    }
    cross_dx, cross_dy = _side_to_dir[g.level.tiles[fy][fx].door_side]
    g._maybe_traverse_building_door(cross_dx, cross_dy)
    # Now self.level is target.ground.
    assert g.level is target.ground
    # The depth-keyed cache for this site points at target.
    depth1_key = g._cache_key(1)
    assert g._floor_cache[depth1_key][0] is target.ground
    if len(target.floors) >= 2:
        depth2_key = g._cache_key(2)
        assert g._floor_cache[depth2_key][0] is target.floors[1]

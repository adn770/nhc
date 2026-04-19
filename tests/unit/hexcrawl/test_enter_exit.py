"""Enter / exit a procedural dungeon from a feature hex.

Tests three things:

* ``dungeon_seed(world_seed, coord, template)`` is a pure
  deterministic hash.
* ``Game.enter_hex_feature(coord)`` generates a dungeon (or
  restores one from the floor cache), switches ``game.level`` out
  of ``None``, and freezes the day clock.
* ``Game.exit_dungeon_to_hex()`` clears the level and puts us back
  on the overland.
"""

from __future__ import annotations

import pytest

from nhc.core.autosave import has_autosave
from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import DungeonRef, HexFeatureType
from nhc.hexcrawl.seed import dungeon_seed
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
    g = Game(
        client=_FakeClient(),
        backend=None,
        game_mode="classic",
        world_mode=mode,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


def _attach_cave(g: Game, coord: HexCoord) -> None:
    """Decorate a hex with a procedural cave so enter_hex_feature
    has something to load."""
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.CAVE
    cell.dungeon = DungeonRef(template="procedural:cave", depth=1)
    # Make sure the player is standing on the feature hex.
    g.hex_player_position = coord


# ---------------------------------------------------------------------------
# dungeon_seed helper
# ---------------------------------------------------------------------------


def test_dungeon_seed_is_deterministic() -> None:
    a = dungeon_seed(42, HexCoord(3, 5), "procedural:cave")
    b = dungeon_seed(42, HexCoord(3, 5), "procedural:cave")
    assert a == b


def test_dungeon_seed_different_for_different_coords() -> None:
    a = dungeon_seed(42, HexCoord(3, 5), "procedural:cave")
    b = dungeon_seed(42, HexCoord(3, 6), "procedural:cave")
    assert a != b


def test_dungeon_seed_different_for_different_templates() -> None:
    a = dungeon_seed(42, HexCoord(3, 5), "procedural:cave")
    b = dungeon_seed(42, HexCoord(3, 5), "procedural:tower")
    assert a != b


def test_dungeon_seed_different_for_different_world_seeds() -> None:
    a = dungeon_seed(1, HexCoord(3, 5), "procedural:cave")
    b = dungeon_seed(2, HexCoord(3, 5), "procedural:cave")
    assert a != b


def test_dungeon_seed_fits_in_uint32() -> None:
    s = dungeon_seed(10 ** 9, HexCoord(-100, 100), "procedural:cave")
    assert 0 <= s < (1 << 32)


# ---------------------------------------------------------------------------
# enter_hex_feature
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enter_hex_feature_generates_dungeon(tmp_path) -> None:
    g = _make_game(tmp_path)
    target = HexCoord(0, 0)
    _attach_cave(g, target)
    assert g.level is None
    ok = await g.enter_hex_feature()
    assert ok
    assert g.level is not None
    assert g.level.width > 0 and g.level.height > 0


@pytest.mark.asyncio
async def test_enter_hex_feature_requires_feature_with_dungeon(tmp_path) -> None:
    g = _make_game(tmp_path)
    # Player is on the hub (CITY feature) but no DungeonRef attached.
    g.hex_world.cells[g.hex_player_position].dungeon = None
    ok = await g.enter_hex_feature()
    assert not ok
    assert g.level is None


@pytest.mark.asyncio
async def test_enter_hex_feature_does_not_advance_day_clock(tmp_path) -> None:
    g = _make_game(tmp_path)
    _attach_cave(g, HexCoord(0, 0))
    day0, time0 = g.hex_world.day, g.hex_world.time
    await g.enter_hex_feature()
    assert (g.hex_world.day, g.hex_world.time) == (day0, time0)


@pytest.mark.asyncio
async def test_enter_hex_feature_is_seed_reproducible(tmp_path) -> None:
    g1 = _make_game(tmp_path)
    _attach_cave(g1, HexCoord(0, 0))
    await g1.enter_hex_feature()
    layout1 = (g1.level.width, g1.level.height, len(g1.level.rooms))

    g2 = _make_game(tmp_path / "sub2")
    _attach_cave(g2, HexCoord(0, 0))
    await g2.enter_hex_feature()
    layout2 = (g2.level.width, g2.level.height, len(g2.level.rooms))

    assert layout1 == layout2


# ---------------------------------------------------------------------------
# exit_dungeon_to_hex
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exit_dungeon_clears_level_and_returns_to_overland(tmp_path) -> None:
    g = _make_game(tmp_path)
    _attach_cave(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    assert g.level is not None
    ok = await g.exit_dungeon_to_hex()
    assert ok
    assert g.level is None
    # hex_world / position are unchanged by the round trip.
    assert g.hex_world is not None
    assert g.hex_player_position == HexCoord(0, 0)


@pytest.mark.asyncio
async def test_exit_without_active_dungeon_is_noop(tmp_path) -> None:
    g = _make_game(tmp_path)
    assert g.level is None
    ok = await g.exit_dungeon_to_hex()
    # Nothing to exit; explicit False so callers can react.
    assert not ok


# ---------------------------------------------------------------------------
# Floor cache interplay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_re_enter_hex_feature_reuses_cached_floor(tmp_path) -> None:
    g = _make_game(tmp_path)
    _attach_cave(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    level_first = g.level
    await g.exit_dungeon_to_hex()
    # Re-enter the same hex. The floor cache (keyed by (q, r, depth))
    # should hand back the same Level instance, not regenerate.
    await g.enter_hex_feature()
    assert g.level is level_first


# ---------------------------------------------------------------------------
# Template wiring through enter_hex_feature
# ---------------------------------------------------------------------------


def _attach_feature(
    g: Game, coord: HexCoord, feature: HexFeatureType, template: str,
) -> None:
    """Attach a feature with a specific template to a hex."""
    cell = g.hex_world.cells[coord]
    cell.feature = feature
    cell.dungeon = DungeonRef(template=template, depth=1)
    g.hex_player_position = coord


@pytest.mark.asyncio
async def test_tower_template_passes_through(tmp_path) -> None:
    """Entering a tower hex sets params.template so the pipeline
    applies StructuralTemplate overrides."""
    g = _make_game(tmp_path)
    _attach_feature(g, HexCoord(0, 0), HexFeatureType.TOWER,
                    "procedural:tower")
    await g.enter_hex_feature()
    assert g.level is not None
    assert g.generation_params is not None
    assert g.generation_params.template == "procedural:tower"


@pytest.mark.asyncio
async def test_crypt_template_passes_through(tmp_path) -> None:
    """Entering a crypt/graveyard hex sets params.template."""
    g = _make_game(tmp_path)
    _attach_feature(g, HexCoord(0, 0), HexFeatureType.GRAVEYARD,
                    "procedural:crypt")
    await g.enter_hex_feature()
    assert g.level is not None
    assert g.generation_params is not None
    assert g.generation_params.template == "procedural:crypt"


@pytest.mark.asyncio
async def test_village_uses_settlement_generator(tmp_path) -> None:
    """Entering a village hex uses SettlementGenerator."""
    g = _make_game(tmp_path)
    _attach_feature(g, HexCoord(0, 0), HexFeatureType.VILLAGE,
                    "procedural:settlement")
    # Set size_class on the dungeon ref
    g.hex_world.cells[HexCoord(0, 0)].dungeon.size_class = "village"
    await g.enter_hex_feature()
    assert g.level is not None
    assert g.level.metadata.theme == "settlement"
    assert g.level.width == 40
    assert g.level.height == 30
    # Should have streets
    street_tiles = sum(
        1 for row in g.level.tiles for t in row if t.is_street
    )
    assert street_tiles > 0



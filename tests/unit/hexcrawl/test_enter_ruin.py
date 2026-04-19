"""Ruin-hex entry (milestone 6).

A hex with ``site_kind="ruin"`` must route through the ruin site
assembler: land on the surface, spawn hostile creatures there,
and cache the surface level. Descent entry (the building's
mandatory 3-floor drop) lands in milestone 7.
"""

from __future__ import annotations

import asyncio

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import (
    Biome, DungeonRef, HexCell, HexFeatureType, HexWorld,
)
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
def _bootstrap() -> None:
    i18n_init("en")
    EntityRegistry.discover_all()


def _make_game(tmp_path) -> Game:
    return Game(
        client=_FakeClient(), backend=None,
        game_mode="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path, seed=42,
    )


def _seed_ruin_cell(g: Game, biome: Biome = Biome.FOREST) -> HexCell:
    g.hex_world = HexWorld(
        pack_id="t", seed=42, width=1, height=1,
    )
    cell = HexCell(
        coord=HexCoord(0, 0), biome=biome,
        feature=HexFeatureType.RUIN,
        dungeon=DungeonRef(
            template="procedural:ruin",
            site_kind="ruin",
            faction="goblin",
        ),
    )
    g.hex_world.set_cell(cell)
    g.hex_world.visit(cell.coord)
    return cell


def test_enter_ruin_hex_lands_on_surface_with_stairs_down(
    tmp_path,
) -> None:
    g = _make_game(tmp_path)
    cell = _seed_ruin_cell(g)

    async def _run() -> None:
        entered = await g._enter_walled_site(cell.coord, "ruin")
        assert entered is True
        assert g._active_site is not None
        assert g._active_site.kind == "ruin"
        # Ground floor of the single ruin building holds the
        # descent stairs_down tile.
        b = g._active_site.buildings[0]
        ground = b.ground
        stairs = [
            (x, y)
            for y in range(ground.height)
            for x in range(ground.width)
            if ground.tiles[y][x].feature == "stairs_down"
        ]
        assert len(stairs) == 1

    asyncio.run(_run())


def test_enter_ruin_surface_is_populated_with_hostile_creatures(
    tmp_path,
) -> None:
    g = _make_game(tmp_path)
    cell = _seed_ruin_cell(g)

    async def _run() -> None:
        entered = await g._enter_walled_site(cell.coord, "ruin")
        assert entered is True
        creatures = [
            e for e in g._active_site.surface.entities
            if e.entity_type == "creature"
        ]
        assert creatures, (
            "ruin surface must be populated with hostile "
            "creatures after assembly"
        )

    asyncio.run(_run())

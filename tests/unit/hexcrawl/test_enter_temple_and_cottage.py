"""Game-layer routing for temple + cottage site hexes (milestone 5).

A temple hex with ``site_kind="temple"`` must dispatch through
``assemble_site("temple", ...)`` and land the player on the
temple surface. Same for cottage. Exercises the four temple
biomes and the forest cottage biome.
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


def _seed_cell(
    g: Game, biome: Biome,
    feature: HexFeatureType, site_kind: str,
    template: str,
) -> HexCell:
    g.hex_world = HexWorld(
        pack_id="t", seed=42, width=1, height=1,
    )
    cell = HexCell(
        coord=HexCoord(0, 0), biome=biome,
        feature=feature,
        dungeon=DungeonRef(
            template=template,
            site_kind=site_kind,
        ),
    )
    g.hex_world.set_cell(cell)
    g.hex_world.visit(cell.coord)
    return cell


# ---------------------------------------------------------------------------
# Temple entry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "biome",
    [Biome.MOUNTAIN, Biome.FOREST, Biome.SANDLANDS, Biome.ICELANDS],
)
def test_enter_temple_hex_routes_through_temple_assembler(
    tmp_path, biome: Biome,
) -> None:
    g = _make_game(tmp_path)
    cell = _seed_cell(
        g, biome, HexFeatureType.TEMPLE, "temple",
        "site:temple",
    )

    async def _run() -> None:
        entered = await g._enter_walled_site(cell.coord, "temple")
        assert entered is True
        assert g._active_site is not None
        assert g._active_site.kind == "temple"
        assert len(g._active_site.buildings) == 1

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Cottage entry
# ---------------------------------------------------------------------------


def test_enter_cottage_hex_routes_through_cottage_assembler(
    tmp_path,
) -> None:
    g = _make_game(tmp_path)
    cell = _seed_cell(
        g, Biome.FOREST, HexFeatureType.COTTAGE, "cottage",
        "site:cottage",
    )

    async def _run() -> None:
        entered = await g._enter_walled_site(cell.coord, "cottage")
        assert entered is True
        assert g._active_site is not None
        assert g._active_site.kind == "cottage"
        assert len(g._active_site.buildings) == 1

    asyncio.run(_run())

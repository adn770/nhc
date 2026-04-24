"""M12 post-apply invariant: no WALL tile inside a building
footprint.

After every partitioner emits only edges and doors, the shell
composer is the single source of ``Terrain.WALL`` tiles. This
test assembles many building sites across seeds and asserts the
invariant — regressions show up loud if anyone re-introduces a
tile-wall path inside a footprint.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import Terrain
from nhc.sites.cottage import assemble_cottage
from nhc.sites.mage_residence import assemble_mage_residence
from nhc.sites.tower import assemble_tower


_ASSEMBLERS = [
    ("cottage", assemble_cottage),
    ("tower", assemble_tower),
    ("mage_residence", assemble_mage_residence),
]


@pytest.mark.parametrize("name, assemble", _ASSEMBLERS)
def test_no_wall_tile_inside_footprint(name, assemble) -> None:
    for seed in range(30):
        site = assemble(f"{name}_{seed}", random.Random(seed))
        for building in site.buildings:
            footprint = building.base_shape.floor_tiles(
                building.base_rect,
            )
            for floor in building.floors:
                for (x, y) in footprint:
                    tile = floor.tiles[y][x]
                    assert tile.terrain is not Terrain.WALL, (
                        f"{name} seed={seed} building={building.id} "
                        f"floor={floor.id}: tile ({x}, {y}) inside "
                        f"the footprint is a WALL — no partitioner "
                        f"should emit WALL tiles after M12"
                    )

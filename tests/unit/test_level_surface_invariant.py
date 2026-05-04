"""Level surface contract — 1-tile VOID margin invariant.

Every level-producing generator (site assembler, dungeon
pipeline, building floor builder) is expected to produce a level
whose renderable bbox sits inside ``[1, w - 2] × [1, h - 2]`` of
the level grid. See ``design/level_surface_layout.md``.

The contract test parametrises every generator entry point and
asserts the invariant. Generators that don't yet comply are
marked ``xfail(strict=True)``; each refactor commit removes its
own xfail. See ``~/src/plans/level_surface_layout_refactor.md``
for the per-commit ladder.
"""

from __future__ import annotations

import random
from typing import Callable

import pytest

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.model import Level
from nhc.dungeon.pipeline import generate_level
from nhc.sites._layout import RenderableBBox, compute_renderable_bbox
from nhc.sites._site import Site, assemble_site
from nhc.sites.town import assemble_town


_BuildResult = tuple[Level, "Site | None"]
_BuildFn = Callable[[int], _BuildResult]


def _site(kind: str) -> _BuildFn:
    def build(seed: int) -> _BuildResult:
        rng = random.Random(seed)
        site = assemble_site(kind, f"site_{kind}_seed{seed}", rng)
        return site.surface, site

    return build


def _town(size_class: str) -> _BuildFn:
    def build(seed: int) -> _BuildResult:
        rng = random.Random(seed)
        site = assemble_town(
            f"town_{size_class}_seed{seed}", rng,
            size_class=size_class,
        )
        return site.surface, site

    return build


def _bsp(seed: int) -> _BuildResult:
    params = GenerationParams(seed=seed, width=80, height=40)
    return generate_level(params), None


def _cellular(seed: int) -> _BuildResult:
    params = GenerationParams(
        seed=seed, width=80, height=40, theme="cave",
    )
    return generate_level(params), None


def _template(name: str) -> _BuildFn:
    def build(seed: int) -> _BuildResult:
        params = GenerationParams(
            seed=seed, width=80, height=40, template=name,
        )
        return generate_level(params), None

    return build


def _theme(name: str) -> _BuildFn:
    def build(seed: int) -> _BuildResult:
        params = GenerationParams(
            seed=seed, width=80, height=40, theme=name,
        )
        return generate_level(params), None

    return build


_ALL_GENERATORS: list[tuple[str, _BuildFn]] = [
    ("site:tower", _site("tower")),
    ("site:farm", _site("farm")),
    ("site:mansion", _site("mansion")),
    ("site:keep", _site("keep")),
    ("site:temple", _site("temple")),
    ("site:cottage", _site("cottage")),
    ("site:ruin", _site("ruin")),
    ("site:mage_residence", _site("mage_residence")),
    ("site:town:hamlet", _town("hamlet")),
    ("site:town:village", _town("village")),
    ("site:town:town", _town("town")),
    ("site:town:city", _town("city")),
    ("dungeon:bsp", _bsp),
    ("dungeon:cellular", _cellular),
    ("template:tower", _template("procedural:tower")),
    ("template:crypt", _template("procedural:crypt")),
    ("template:mine", _template("procedural:mine")),
    ("theme:cave", _theme("cave")),
    ("theme:fungal_cavern", _theme("fungal_cavern")),
    ("theme:lava_chamber", _theme("lava_chamber")),
    ("theme:underground_lake", _theme("underground_lake")),
]


# Generators that don't yet satisfy the 1-tile VOID margin
# contract. Each entry is removed in its own refactor commit.
# Town (all four size classes) is fixed in this commit; cellular
# and ``theme:cave`` (its companion biome) await the dungeon-side
# audit pass in a later commit. ``site:keep`` and ``site:ruin``
# already satisfy the contract — their enclosure polygons
# contribute their max-edge-coord-1 to the bbox so the
# fortification ring stays inside the 1-tile margin even though
# the surface is over-allocated relative to the rendered
# content. Tightening that over-allocation is a separate
# concern; the contract test does not gate it.
_XFAIL: set[str] = {
    "dungeon:cellular",
    "theme:cave",
}


@pytest.mark.parametrize("seed", [7, 42, 99])
@pytest.mark.parametrize(
    "name,build", _ALL_GENERATORS,
    ids=[name for name, _ in _ALL_GENERATORS],
)
def test_renderable_bbox_inside_surface(
    name: str, build: _BuildFn, seed: int,
    request: pytest.FixtureRequest,
) -> None:
    if name in _XFAIL:
        request.node.add_marker(
            pytest.mark.xfail(
                strict=True,
                reason=(
                    f"{name} awaits refactor "
                    "(plans/level_surface_layout_refactor.md)"
                ),
            ),
        )
    level, site = build(seed)
    bbox = compute_renderable_bbox(level, site)
    assert not bbox.empty, f"{name}@{seed}: empty renderable bbox"
    assert bbox.min_x >= 1, (
        f"{name}@{seed}: bbox.min_x={bbox.min_x} < 1"
    )
    assert bbox.min_y >= 1, (
        f"{name}@{seed}: bbox.min_y={bbox.min_y} < 1"
    )
    assert bbox.max_x <= level.width - 2, (
        f"{name}@{seed}: bbox.max_x={bbox.max_x} > "
        f"width-2={level.width - 2}"
    )
    assert bbox.max_y <= level.height - 2, (
        f"{name}@{seed}: bbox.max_y={bbox.max_y} > "
        f"height-2={level.height - 2}"
    )


def test_renderable_bbox_helper_handles_empty_site() -> None:
    """``compute_renderable_bbox`` returns an explicit empty bbox
    when the level is all VOID and no site is supplied — callers
    are expected to treat ``empty == True`` as a contract failure
    rather than silently passing."""
    level = Level.create_empty("blank", "blank", 0, 5, 5)
    bbox = compute_renderable_bbox(level)
    assert bbox.empty


def test_renderable_bbox_includes_polygon_and_overhang() -> None:
    """Sanity test for the helper: polygon vertices contribute as
    edge coords (max-1) and building rects grow by 1 tile on each
    side."""
    from nhc.dungeon.building import Building
    from nhc.dungeon.model import Rect, RectShape, Tile, Terrain
    from nhc.sites._site import Enclosure

    level = Level.create_empty("blank", "blank", 0, 20, 20)
    # Single floor tile so the non-VOID scan returns a hit.
    level.tiles[10][10] = Tile(terrain=Terrain.FLOOR)
    enc = Enclosure(
        kind="palisade",
        polygon=[(2, 3), (15, 3), (15, 14), (2, 14)],
    )
    b = Building(
        id="b0",
        base_shape=RectShape(),
        base_rect=Rect(5, 6, 4, 3),
        floors=[],
    )
    site = Site(
        id="s",
        kind="town",
        buildings=[b],
        surface=level,
        enclosure=enc,
    )
    bbox = compute_renderable_bbox(level, site)
    # Polygon contribution: x in [2, 14], y in [3, 13] (max-1).
    # Building contribution: x in [4, 9], y in [5, 9] (rect ± 1).
    # Floor tile contribution: (10, 10).
    # Union: x in [2, 14], y in [3, 13].
    assert (bbox.min_x, bbox.min_y) == (2, 3)
    assert (bbox.max_x, bbox.max_y) == (14, 13)

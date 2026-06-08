"""Pin the v5 fixture emit order to canopy height.

Vegetation features stack by how tall they grow: flowers sit on
the ground, bushes are shrub height, trees raise a canopy above
both. Because the painter walks ``ops[]`` linearly and later ops
paint on top (``map_ir_v5.md`` §10.4), the emitter must emit the
shortest features first and the tallest last so a tree's canopy
covers the flowers and bushes planted beneath it.
"""

from __future__ import annotations

from types import SimpleNamespace

from nhc.dungeon.model import Level
from nhc.rendering.emit.fixture import emit_fixtures
from nhc.rendering.ir._fb.FixtureKind import FixtureKind


def _level_with_features(features: dict[tuple[int, int], str]) -> Level:
    level = Level.create_empty("test", "Test", 0, width=8, height=8)
    for (x, y), feat in features.items():
        level.tile_at(x, y).feature = feat
    return level


def _emit_kinds(level: Level) -> list[int]:
    builder = SimpleNamespace(ctx=SimpleNamespace(level=level, seed=99))
    return [entry.op.kind for entry in emit_fixtures(builder)]


def test_flowers_emit_before_bushes_before_trees() -> None:
    # One flower, one bush, one isolated tree — all distinct tiles.
    level = _level_with_features({
        (1, 1): "flower",
        (3, 3): "bush",
        (5, 5): "tree",
    })

    kinds = _emit_kinds(level)

    assert FixtureKind.Flower in kinds
    assert FixtureKind.Bush in kinds
    assert FixtureKind.Tree in kinds
    assert kinds.index(FixtureKind.Flower) < kinds.index(FixtureKind.Bush)
    assert kinds.index(FixtureKind.Bush) < kinds.index(FixtureKind.Tree)


def test_trees_emit_last_so_canopy_covers_understory() -> None:
    # A tree grove (3+ connected tiles emits a second Tree op) plus a
    # flower bed: every Tree op must follow the Flower op.
    level = _level_with_features({
        (0, 0): "flower",
        (1, 0): "flower",
        (4, 4): "tree",
        (5, 4): "tree",
        (4, 5): "tree",  # 3-tile grove → grove op
    })

    kinds = _emit_kinds(level)

    last_flower = max(
        i for i, k in enumerate(kinds) if k == FixtureKind.Flower
    )
    first_tree = min(
        i for i, k in enumerate(kinds) if k == FixtureKind.Tree
    )
    assert last_flower < first_tree


def test_ground_structures_stay_below_vegetation() -> None:
    # Stairs / wells / fountains are ground fixtures; vegetation
    # canopies should still paint over them.
    level = _level_with_features({
        (2, 2): "well",
        (3, 3): "fountain",
        (6, 6): "flower",
        (7, 7): "tree",
    })

    kinds = _emit_kinds(level)

    veg_start = min(
        i for i, k in enumerate(kinds)
        if k in (FixtureKind.Flower, FixtureKind.Tree)
    )
    structures = {FixtureKind.Well, FixtureKind.Fountain}
    assert all(
        i < veg_start for i, k in enumerate(kinds) if k in structures
    )

"""M2: tree grove merging.

Trees touching 4-adjacently form connected components. Single
trees and pairs keep the per-tile fragment path (so the visual
weight of two separate trunks reads); groves of 3+ collapse into
a single Shapely-unioned silhouette so the canopies fuse into
one organic mass like the cartographer maps in
``docs/maps/PalisadeTown2.jpg``.
"""

from __future__ import annotations

import re

from nhc.dungeon.generators.cellular import CaveShape
from nhc.dungeon.model import (
    Level, Rect, Room, SurfaceType, Terrain, Tile,
)
from nhc.rendering._features_svg import (
    _connected_tree_groves, _canopy_fill_jitter,
    render_tree_features,
)
from nhc.rendering._svg_helpers import CELL
from nhc.rendering.svg import render_floor_svg


def _level_with_features(
    features: list[tuple[int, int, str]],
    width: int = 12, height: int = 12,
) -> Level:
    level = Level.create_empty("L", "L", 0, width, height)
    for y in range(height):
        for x in range(width):
            level.tiles[y][x] = Tile(
                terrain=Terrain.FLOOR,
                surface_type=SurfaceType.FIELD,
            )
    for x, y, feat in features:
        level.tiles[y][x] = Tile(
            terrain=Terrain.FLOOR,
            surface_type=SurfaceType.FIELD,
            feature=feat,
        )
    return level


def _floor_grid(w: int, h: int) -> Level:
    level = Level.create_empty("L", "L", 1, w, h)
    for y in range(h):
        for x in range(w):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [Room(id="r1", rect=Rect(0, 0, w, h))]
    return level


# ── 1. Connected components / 4-adjacency BFS ────────────────


class TestConnectedComponents:
    def test_isolated_tree_is_size_1_grove(self) -> None:
        level = _level_with_features([(3, 3, "tree")])
        groves = _connected_tree_groves(level)
        assert len(groves) == 1
        assert groves[0] == frozenset([(3, 3)])

    def test_two_orthogonal_trees_form_size_2(self) -> None:
        level = _level_with_features([
            (3, 3, "tree"), (3, 4, "tree"),
        ])
        groves = _connected_tree_groves(level)
        assert len(groves) == 1
        assert len(groves[0]) == 2

    def test_three_in_a_row_form_size_3(self) -> None:
        level = _level_with_features([
            (3, 3, "tree"), (4, 3, "tree"), (5, 3, "tree"),
        ])
        groves = _connected_tree_groves(level)
        assert len(groves) == 1
        assert len(groves[0]) == 3

    def test_diagonal_neighbours_are_separate_groves(self) -> None:
        level = _level_with_features([
            (3, 3, "tree"), (4, 4, "tree"),
        ])
        groves = _connected_tree_groves(level)
        # Diagonal-only adjacency does NOT merge groves.
        assert len(groves) == 2
        for grove in groves:
            assert len(grove) == 1


# ── 2. Small groves stay stacked ─────────────────────────────


class TestSmallGroveStaysStacked:
    def test_size_1_emits_per_tile_fragment(self) -> None:
        level = _level_with_features([(3, 3, "tree")])
        fragments = render_tree_features(level)
        # Per-tile fragment uses class="tree-feature", not
        # tree-grove.
        assert len(fragments) == 1
        assert "tree-feature" in fragments[0]
        assert "tree-grove" not in fragments[0]

    def test_size_2_emits_two_per_tile_fragments(self) -> None:
        level = _level_with_features([
            (3, 3, "tree"), (3, 4, "tree"),
        ])
        fragments = render_tree_features(level)
        assert len(fragments) == 2
        for frag in fragments:
            assert "tree-feature" in frag
            assert "tree-grove" not in frag


# ── 3. Large grove fuses canopies ────────────────────────────


class TestLargeGroveUnionsCanopies:
    def test_size_3_emits_one_grove_fragment(self) -> None:
        level = _level_with_features([
            (3, 3, "tree"), (4, 3, "tree"), (5, 3, "tree"),
        ])
        fragments = render_tree_features(level)
        # Grove of 3 collapses to a single fragment.
        assert len(fragments) == 1
        assert "tree-grove" in fragments[0]

    def test_grove_fragment_is_anchored_to_min_tile(self) -> None:
        level = _level_with_features([
            (5, 7, "tree"), (4, 7, "tree"), (3, 7, "tree"),
        ])
        fragments = render_tree_features(level)
        # min((3,7), (4,7), (5,7)) = (3, 7).
        assert "tree-grove-3-7" in fragments[0]

    def test_grove_fragment_d_string_is_a_union_polygon(self) -> None:
        """A 3-in-a-row grove's canopy union should span at least
        2*CELL of horizontal extent, since the chain spans 3 tile
        centres + canopy radius on each end."""
        level = _level_with_features([
            (3, 5, "tree"), (4, 5, "tree"), (5, 5, "tree"),
        ])
        svg = render_tree_features(level)[0]
        m = re.search(r'class="tree-canopy"[^/]*d="([^"]+)"', svg)
        assert m, f"tree-canopy not found in: {svg[:300]}"
        d = m.group(1)
        coords = [
            (float(x), float(y))
            for x, y in re.findall(
                r"[ML](-?\d+\.\d+),(-?\d+\.\d+)", d,
            )
        ]
        assert coords, "expected coords parsed from d-string"
        xs = [x for x, _ in coords]
        x_extent = max(xs) - min(xs)
        # 3-in-a-row: 2 cells between centres + canopy on each
        # end. Should easily exceed 2 * CELL.
        assert x_extent > 2 * CELL, (
            f"union x-extent {x_extent:.2f} should span >2*CELL "
            f"({2*CELL:.2f}) for a 3-tile chain"
        )


# ── 4. Per-grove hue is anchor-stable ────────────────────────


class TestGroveHueStability:
    def test_adding_a_fourth_tree_does_not_flip_grove_hue(self):
        """Both groves share the same min anchor (3, 5). Adding
        a 4th tree must not change the canopy fill -- otherwise
        adding/removing a single tree flips hue across the whole
        grove, which reads as a flicker."""
        level3 = _level_with_features([
            (3, 5, "tree"), (4, 5, "tree"), (5, 5, "tree"),
        ])
        level4 = _level_with_features([
            (3, 5, "tree"), (4, 5, "tree"),
            (5, 5, "tree"), (6, 5, "tree"),
        ])
        svg3 = render_tree_features(level3)[0]
        svg4 = render_tree_features(level4)[0]
        m3 = re.search(
            r'class="tree-canopy"[^/]*fill="([^"]+)"', svg3,
        )
        m4 = re.search(
            r'class="tree-canopy"[^/]*fill="([^"]+)"', svg4,
        )
        assert m3 and m4
        # Same anchor (3, 5) -> same hue jitter -> same fill.
        assert m3.group(1) == m4.group(1), (
            f"grove hue should be anchor-stable: {m3.group(1)} "
            f"vs {m4.group(1)}"
        )

    def test_grove_hue_matches_canopy_jitter_at_anchor(self):
        level = _level_with_features([
            (3, 5, "tree"), (4, 5, "tree"), (5, 5, "tree"),
        ])
        svg = render_tree_features(level)[0]
        m = re.search(r'class="tree-canopy"[^/]*fill="([^"]+)"', svg)
        assert m
        expected = _canopy_fill_jitter(3, 5)
        assert m.group(1) == expected, (
            f"grove canopy fill {m.group(1)} != anchor jitter "
            f"{expected}"
        )


# ── 5. Cross-floor-kind portability ──────────────────────────


class TestGrovePortability:
    def _set_grove(self, level: Level) -> None:
        for x, y in [(2, 2), (3, 2), (4, 2)]:
            level.tiles[y][x].feature = "tree"

    def test_grove_paints_on_dungeon(self) -> None:
        level = _floor_grid(8, 8)
        self._set_grove(level)
        svg = render_floor_svg(level)
        assert "tree-grove" in svg

    def test_grove_paints_on_building(self) -> None:
        level = _floor_grid(8, 8)
        level.building_id = "b1"
        self._set_grove(level)
        svg = render_floor_svg(level)
        assert "tree-grove" in svg

    def test_grove_paints_on_cave(self) -> None:
        level = _floor_grid(8, 8)
        level.rooms = [Room(
            id="cave1",
            rect=Rect(0, 0, 8, 8),
            shape=CaveShape(tiles={
                (x, y) for y in range(8) for x in range(8)
            }),
        )]
        self._set_grove(level)
        svg = render_floor_svg(level, seed=11)
        assert "tree-grove" in svg

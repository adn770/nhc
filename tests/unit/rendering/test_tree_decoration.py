"""SVG tree decoration (Phase 4b).

Mirrors the well / fountain pattern -- ``tree`` tiles get a
soft green canopy + brown trunk dot baked into the floor SVG so
the periphery vegetation reads on the surface map even before
any entity is overlaid client-side. See
``town_redesign_plan.md`` Phase 4b for the design.
"""

from __future__ import annotations

from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.rendering._features_svg import (
    TREE_CANOPY_FILL, render_tree_features,
)
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


# ── 1. Each tree tile emits one fragment ──────────────────────


class TestRenderTreeFeatures:
    def test_one_fragment_per_tree_tile(self):
        level = _level_with_features([
            (3, 3, "tree"), (5, 3, "tree"), (8, 6, "tree"),
        ])
        fragments = render_tree_features(level)
        assert len(fragments) == 3

    def test_returns_empty_when_no_tree_tiles(self):
        level = _level_with_features([
            (3, 3, "well"), (5, 5, "fountain"),
        ])
        assert render_tree_features(level) == []

    def test_dispatcher_ignores_unrelated_features(self):
        """Only ``tree`` dispatches; well / fountain / campfire
        flow through their own dispatchers and don't leak into
        the tree pass."""
        level = _level_with_features([
            (3, 3, "tree"), (5, 5, "well"),
            (7, 7, "fountain"), (9, 9, "campfire"),
        ])
        fragments = render_tree_features(level)
        assert len(fragments) == 1


# ── 2. Fragment carries canopy + trunk classes ────────────────


class TestTreeFragmentShape:
    def test_fragment_has_canopy_and_trunk(self):
        level = _level_with_features([(4, 4, "tree")])
        fragments = render_tree_features(level)
        assert len(fragments) == 1
        svg = fragments[0]
        assert "tree-canopy" in svg, (
            "tree fragment should carry a canopy class"
        )
        assert "tree-trunk" in svg, (
            "tree fragment should carry a trunk class"
        )

    def test_canopy_uses_field_tinted_fill(self):
        level = _level_with_features([(4, 4, "tree")])
        svg = render_tree_features(level)[0]
        assert TREE_CANOPY_FILL in svg, (
            f"canopy fragment missing canopy fill "
            f"{TREE_CANOPY_FILL!r}"
        )


# ── 3. Same-seed determinism ──────────────────────────────────


class TestDeterminism:
    def test_same_tile_same_fragment(self):
        level = _level_with_features([(4, 4, "tree")])
        a = render_tree_features(level)[0]
        b = render_tree_features(level)[0]
        assert a == b, (
            "same tile should render the same canopy outline"
        )

    def test_different_tiles_render_different_fragments(self):
        level_a = _level_with_features([(4, 4, "tree")])
        level_b = _level_with_features([(7, 4, "tree")])
        a = render_tree_features(level_a)[0]
        b = render_tree_features(level_b)[0]
        # Tile centres differ -> the cx/cy attribute strings
        # in the SVG must differ.
        assert a != b


# ── 4. End-to-end via render_floor_svg ────────────────────────


class TestFloorSvgIntegration:
    def test_render_floor_svg_paints_trees(self):
        level = _level_with_features([(4, 4, "tree")])
        svg = render_floor_svg(level, seed=7)
        assert "tree-canopy" in svg
        assert "tree-trunk" in svg

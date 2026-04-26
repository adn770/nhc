"""SVG tree decoration (Phase 4b).

Mirrors the well / fountain pattern -- ``tree`` tiles get a
soft green canopy + brown trunk dot baked into the floor SVG so
the periphery vegetation reads on the surface map even before
any entity is overlaid client-side. See
``town_redesign_plan.md`` Phase 4b for the design.
"""

from __future__ import annotations

import colorsys
import re

from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.rendering._features_svg import (
    TREE_CANOPY_FILL,
    TREE_CANOPY_RADIUS,
    TREE_CANOPY_SHADOW_FILL,
    TREE_VOLUME_MARK_COUNT,
    render_tree_features,
)
from nhc.rendering._svg_helpers import CELL
from nhc.rendering.svg import render_floor_svg


def _hex_to_hls(hex_str: str) -> tuple[float, float, float]:
    """Parse ``#RRGGBB`` into HLS triplet in ``[0, 1]``."""
    s = hex_str.lstrip("#")
    r = int(s[0:2], 16) / 255.0
    g = int(s[2:4], 16) / 255.0
    b = int(s[4:6], 16) / 255.0
    return colorsys.rgb_to_hls(r, g, b)


def _extract_canopy_fill(svg: str) -> str:
    """Return the fill="..." colour on the ``tree-canopy`` path."""
    m = re.search(
        r'class="tree-canopy"[^/]*fill="([^"]+)"', svg,
    )
    assert m, f"tree-canopy not found in: {svg[:200]}"
    return m.group(1)


def _extract_attr(svg: str, cls: str, attr: str) -> str:
    """Return ``attr="..."`` from the element matching ``class=cls``."""
    pattern = rf'class="{re.escape(cls)}"[^/]*{attr}="([^"]+)"'
    m = re.search(pattern, svg)
    assert m, f"missing {attr} on class={cls!r} in: {svg[:200]}"
    return m.group(1)


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
        """Canopy fill is in the green family rather than equal
        to a literal hex (M1 introduces per-tile hue jitter)."""
        level = _level_with_features([(4, 4, "tree")])
        svg = render_tree_features(level)[0]
        fill = _extract_canopy_fill(svg)
        h, l, s = _hex_to_hls(fill)
        # Hue ~ 90deg (green family); Lightness 25-60%.
        hue_deg = h * 360.0
        light_pct = l * 100.0
        assert 70.0 <= hue_deg <= 110.0, (
            f"canopy fill hue out of green band: {hue_deg:.1f}deg"
        )
        assert 25.0 <= light_pct <= 60.0, (
            f"canopy fill lightness out of band: {light_pct:.1f}%"
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


# ── 5. Volume marks (interior leaf-cluster shadows) ──────────


def _extract_all_attrs(
    svg: str, cls: str, attr: str,
) -> list[str]:
    """All ``attr="..."`` values for elements matching class=cls."""
    pattern = rf'class="{re.escape(cls)}"[^/]*{attr}="([^"]+)"'
    return re.findall(pattern, svg)


class TestTreeVolumeMarks:
    def test_fragment_has_volume_class(self):
        level = _level_with_features([(4, 4, "tree")])
        svg = render_tree_features(level)[0]
        assert "tree-volume" in svg, (
            "tree fragment should carry inner volume marks"
        )

    def test_volume_mark_count_matches_constant(self):
        level = _level_with_features([(4, 4, "tree")])
        svg = render_tree_features(level)[0]
        count = svg.count('class="tree-volume"')
        assert count == TREE_VOLUME_MARK_COUNT, (
            f"expected {TREE_VOLUME_MARK_COUNT} volume marks, "
            f"got {count}"
        )

    def test_volume_marks_are_fill_none(self):
        level = _level_with_features([(4, 4, "tree")])
        svg = render_tree_features(level)[0]
        fills = _extract_all_attrs(svg, "tree-volume", "fill")
        assert fills
        for fill in fills:
            assert fill == "none", (
                f"volume marks must be stroke-only, got "
                f"fill={fill!r}"
            )

    def test_volume_marks_use_dasharray(self):
        level = _level_with_features([(4, 4, "tree")])
        svg = render_tree_features(level)[0]
        dashes = _extract_all_attrs(
            svg, "tree-volume", "stroke-dasharray",
        )
        assert len(dashes) == TREE_VOLUME_MARK_COUNT

    def test_volume_marks_use_arc_path(self):
        """Volume marks are arcs (``A`` command in d-string),
        not closed polygons. Discontinuous by construction."""
        level = _level_with_features([(4, 4, "tree")])
        svg = render_tree_features(level)[0]
        ds = _extract_all_attrs(svg, "tree-volume", "d")
        assert ds
        for d in ds:
            assert " A" in d or "A" in d.split("M")[1], (
                f"volume mark should contain an arc command, "
                f"got d={d!r}"
            )
            assert "Z" not in d, (
                f"volume mark must be open, got d={d!r}"
            )

    def test_volume_marks_inside_canopy_area(self):
        """Each mark's start/end points must sit inside the
        outer canopy footprint."""
        level = _level_with_features([(4, 4, "tree")])
        svg = render_tree_features(level)[0]
        ds = _extract_all_attrs(svg, "tree-volume", "d")
        cx = 4.5 * CELL
        cy = 4.5 * CELL
        # Outer extent of canopy = cluster + lobe radii
        # (~0.62 cell). Slack for jitter overhead.
        max_radius = 0.75 * CELL
        for d in ds:
            coords = re.findall(
                r"[ML](-?\d+\.\d+),(-?\d+\.\d+)", d,
            )
            assert coords
            for sx, sy in coords:
                px, py = float(sx), float(sy)
                dist = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
                assert dist < max_radius, (
                    f"volume mark point ({px:.2f},{py:.2f}) at "
                    f"distance {dist:.2f} exceeds canopy area "
                    f"{max_radius:.2f}"
                )

    def test_volume_marks_use_silhouette_stroke(self):
        """Volume strokes use the silhouette stroke colour
        (darker than canopy fill) so they read as inner shadow,
        not light."""
        from nhc.rendering._features_svg import (
            TREE_CANOPY_STROKE,
        )
        level = _level_with_features([(4, 4, "tree")])
        svg = render_tree_features(level)[0]
        strokes = _extract_all_attrs(svg, "tree-volume", "stroke")
        assert strokes
        for stroke in strokes:
            assert stroke == TREE_CANOPY_STROKE, (
                f"volume stroke should be {TREE_CANOPY_STROKE}, "
                f"got {stroke}"
            )


# ── 6. M1 silhouette stroke ──────────────────────────────────


class TestTreeStrokePass:
    def test_silhouette_polygon_is_fill_none(self):
        level = _level_with_features([(4, 4, "tree")])
        svg = render_tree_features(level)[0]
        # The silhouette pass must carry fill="none".
        m = re.search(
            r'class="tree-silhouette"[^/]*fill="([^"]+)"', svg,
        )
        assert m, f"tree-silhouette path missing in: {svg[:200]}"
        assert m.group(1) == "none", (
            f"silhouette fill should be 'none', got {m.group(1)!r}"
        )

    def test_silhouette_stroke_alpha_present(self):
        level = _level_with_features([(4, 4, "tree")])
        svg = render_tree_features(level)[0]
        # stroke-opacity attribute on silhouette path.
        m = re.search(
            r'class="tree-silhouette"[^/]*'
            r'stroke-opacity="([^"]+)"',
            svg,
        )
        assert m, (
            f"tree-silhouette stroke-opacity missing in: "
            f"{svg[:200]}"
        )
        alpha = float(m.group(1))
        assert 0.0 < alpha < 1.0, (
            f"silhouette stroke-opacity should be partial alpha, "
            f"got {alpha}"
        )


# ── 7. M1 shadow polygon ─────────────────────────────────────


class TestTreeShadow:
    def test_shadow_polygon_present(self):
        level = _level_with_features([(4, 4, "tree")])
        svg = render_tree_features(level)[0]
        assert "tree-canopy-shadow" in svg, (
            "M1 layered tree should carry a shadow class"
        )
        assert TREE_CANOPY_SHADOW_FILL in svg, (
            f"shadow fill {TREE_CANOPY_SHADOW_FILL!r} missing"
        )

    def test_shadow_lobe_radius_larger_than_canopy_lobe(self):
        """Shadow lobes are sized larger than canopy lobes so the
        shadow peeks out around the silhouette."""
        from nhc.rendering._features_svg import (
            TREE_CANOPY_LOBE_RADIUS,
            TREE_CANOPY_SHADOW_LOBE_RADIUS,
        )
        assert (
            TREE_CANOPY_SHADOW_LOBE_RADIUS > TREE_CANOPY_LOBE_RADIUS
        ), (
            f"shadow lobe radius "
            f"{TREE_CANOPY_SHADOW_LOBE_RADIUS} must be greater "
            f"than canopy lobe radius {TREE_CANOPY_LOBE_RADIUS}"
        )


# ── 8. M1 per-tile hue jitter ────────────────────────────────


class TestPerTreeHueJitter:
    def test_two_distinct_tiles_have_different_canopy_fills(self):
        a = render_tree_features(
            _level_with_features([(4, 4, "tree")]),
        )[0]
        b = render_tree_features(
            _level_with_features([(7, 4, "tree")]),
        )[0]
        fill_a = _extract_canopy_fill(a)
        fill_b = _extract_canopy_fill(b)
        assert fill_a != fill_b, (
            f"adjacent trees should have different jittered fills "
            f"(both = {fill_a})"
        )

    def test_canopy_fill_is_deterministic_per_tile(self):
        a = render_tree_features(
            _level_with_features([(4, 4, "tree")]),
        )[0]
        b = render_tree_features(
            _level_with_features([(4, 4, "tree")]),
        )[0]
        assert _extract_canopy_fill(a) == _extract_canopy_fill(b)

    def test_canopy_fill_distance_within_threshold(self):
        """Per-tile jitter is bounded -- assert every fill in a
        small grid stays within hue +/-10deg, lightness +/-8% of
        the base ``TREE_CANOPY_FILL``."""
        h0, l0, _ = _hex_to_hls(TREE_CANOPY_FILL)
        for tx in range(2, 8):
            for ty in range(2, 8):
                level = _level_with_features([(tx, ty, "tree")])
                svg = render_tree_features(level)[0]
                fill = _extract_canopy_fill(svg)
                h, l, _ = _hex_to_hls(fill)
                # Hue distance on the circle.
                dh = abs((h - h0 + 0.5) % 1.0 - 0.5) * 360.0
                dl = abs(l - l0) * 100.0
                assert dh <= 10.0, (
                    f"tile ({tx},{ty}) hue drift {dh:.1f}deg "
                    f"exceeds +/-10deg from base"
                )
                assert dl <= 8.0, (
                    f"tile ({tx},{ty}) lightness drift {dl:.1f}% "
                    f"exceeds +/-8% from base"
                )

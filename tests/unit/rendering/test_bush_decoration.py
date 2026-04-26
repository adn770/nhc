"""SVG bush decoration (M3).

Mirrors the tree feature: ``bush`` tiles get a smaller pom-pom
canopy with the same per-tile hue jitter + highlight scheme as
the M1 tree refresh, but with no trunk and a slightly lighter
fill family. The canopy stays inside its own tile so a future
placement pass can sit bushes 4-adjacent to building footprints
without bleeding canopy onto roofs (the differentiator from
trees, which need a one-tile clearance).
"""

from __future__ import annotations

import colorsys
import math
import re

from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.rendering._features_svg import (
    BUSH_CANOPY_FILL,
    BUSH_CANOPY_RADIUS,
    BUSH_CANOPY_JITTER_RANGE,
    render_bush_features,
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


def _hex_to_hls(hex_str: str) -> tuple[float, float, float]:
    s = hex_str.lstrip("#")
    r = int(s[0:2], 16) / 255.0
    g = int(s[2:4], 16) / 255.0
    b = int(s[4:6], 16) / 255.0
    return colorsys.rgb_to_hls(r, g, b)


def _extract_attr(svg: str, cls: str, attr: str) -> str:
    pattern = rf'class="{re.escape(cls)}"[^/]*{attr}="([^"]+)"'
    m = re.search(pattern, svg)
    assert m, f"missing {attr} on class={cls!r}"
    return m.group(1)


# ── 1. One fragment per bush tile ────────────────────────────


class TestRenderBushFeatures:
    def test_one_fragment_per_bush_tile(self) -> None:
        level = _level_with_features([
            (3, 3, "bush"), (5, 3, "bush"), (8, 6, "bush"),
        ])
        fragments = render_bush_features(level)
        assert len(fragments) == 3

    def test_returns_empty_when_no_bush_tiles(self) -> None:
        level = _level_with_features([
            (3, 3, "tree"), (5, 5, "well"),
        ])
        assert render_bush_features(level) == []

    def test_dispatcher_ignores_unrelated_features(self) -> None:
        level = _level_with_features([
            (3, 3, "bush"), (4, 4, "tree"), (5, 5, "well"),
            (7, 7, "fountain"), (9, 9, "campfire"),
        ])
        fragments = render_bush_features(level)
        assert len(fragments) == 1


# ── 2. Fragment shape ────────────────────────────────────────


class TestBushFragmentShape:
    def test_fragment_has_bush_canopy_class(self) -> None:
        level = _level_with_features([(4, 4, "bush")])
        svg = render_bush_features(level)[0]
        assert "bush-canopy" in svg

    def test_fragment_has_no_trunk_class(self) -> None:
        level = _level_with_features([(4, 4, "bush")])
        svg = render_bush_features(level)[0]
        assert "trunk" not in svg, (
            "bushes have no trunk -- a trunk class would "
            "betray a copy-pasted tree fragment"
        )

    def test_fragment_uses_bush_fill_family(self) -> None:
        """Bush canopy fill should be in the green family with
        a higher lightness band than the tree base (so bushes
        read as lighter foliage). Per-tile jitter still applies."""
        level = _level_with_features([(4, 4, "bush")])
        svg = render_bush_features(level)[0]
        m = re.search(
            r'class="bush-canopy"[^/]*fill="([^"]+)"', svg,
        )
        assert m, f"bush-canopy fill not found in: {svg[:200]}"
        h, l, _ = _hex_to_hls(m.group(1))
        hue_deg = h * 360.0
        assert 70.0 <= hue_deg <= 110.0, (
            f"bush fill hue out of green band: {hue_deg:.1f}deg"
        )


class TestBushHighlight:
    def test_highlight_offset_upper_left(self) -> None:
        level = _level_with_features([(4, 4, "bush")])
        svg = render_bush_features(level)[0]
        d = _extract_attr(svg, "bush-canopy-highlight", "d")
        coords = [
            (float(x), float(y))
            for x, y in re.findall(
                r"[ML](-?\d+\.\d+),(-?\d+\.\d+)", d,
            )
        ]
        assert coords
        ax = sum(x for x, _ in coords) / len(coords)
        ay = sum(y for _, y in coords) / len(coords)
        cx = 4.5 * CELL
        cy = 4.5 * CELL
        assert ax < cx, (
            f"highlight centroid x {ax:.2f} not left of "
            f"canopy centre {cx:.2f}"
        )
        assert ay < cy, (
            f"highlight centroid y {ay:.2f} not above "
            f"canopy centre {cy:.2f}"
        )


# ── 3. Per-tile jitter ───────────────────────────────────────


class TestPerBushHueJitter:
    def test_distinct_tiles_get_distinct_fills(self) -> None:
        a = render_bush_features(
            _level_with_features([(4, 4, "bush")]),
        )[0]
        b = render_bush_features(
            _level_with_features([(7, 4, "bush")]),
        )[0]
        m_a = re.search(r'class="bush-canopy"[^/]*fill="([^"]+)"', a)
        m_b = re.search(r'class="bush-canopy"[^/]*fill="([^"]+)"', b)
        assert m_a and m_b
        assert m_a.group(1) != m_b.group(1), (
            "adjacent bushes should have different jittered fills"
        )


# ── 4. Canopy stays inside its own tile ──────────────────────


class TestBushCanopyStaysWithinTile:
    def test_every_polygon_point_inside_tile(self) -> None:
        """``radius + jitter`` must stay below ``0.5 * CELL`` so a
        bush placed 4-adjacent to a building footprint doesn't
        leak canopy onto the roof. Belt + braces: parse the path
        and verify."""
        # Sanity check: constants are tuned so radius + jitter
        # < 0.5 * CELL.
        assert (
            BUSH_CANOPY_RADIUS + BUSH_CANOPY_JITTER_RANGE
            < 0.5 * CELL
        ), (
            f"bush canopy may leak: "
            f"r={BUSH_CANOPY_RADIUS}, j={BUSH_CANOPY_JITTER_RANGE}, "
            f"half-cell={0.5 * CELL}"
        )
        for tx in range(2, 8):
            for ty in range(2, 8):
                level = _level_with_features([(tx, ty, "bush")])
                svg = render_bush_features(level)[0]
                d = _extract_attr(svg, "bush-canopy", "d")
                cx = (tx + 0.5) * CELL
                cy = (ty + 0.5) * CELL
                half = 0.5 * CELL
                for sx, sy in re.findall(
                    r"[ML](-?\d+\.\d+),(-?\d+\.\d+)", d,
                ):
                    px = float(sx)
                    py = float(sy)
                    dist = math.hypot(px - cx, py - cy)
                    assert dist < half, (
                        f"point ({px:.2f},{py:.2f}) at distance "
                        f"{dist:.2f} >= half-cell {half:.2f} from "
                        f"tile ({tx},{ty}) centre"
                    )


# ── 5. Determinism ───────────────────────────────────────────


class TestDeterminism:
    def test_same_tile_same_fragment(self) -> None:
        a = render_bush_features(
            _level_with_features([(4, 4, "bush")]),
        )[0]
        b = render_bush_features(
            _level_with_features([(4, 4, "bush")]),
        )[0]
        assert a == b

    def test_different_tiles_render_different_fragments(self):
        a = render_bush_features(
            _level_with_features([(4, 4, "bush")]),
        )[0]
        b = render_bush_features(
            _level_with_features([(7, 4, "bush")]),
        )[0]
        assert a != b


# ── 6. End-to-end via render_floor_svg ───────────────────────


class TestFloorSvgIntegration:
    def test_render_floor_svg_paints_bushes(self) -> None:
        level = _level_with_features([(4, 4, "bush")])
        svg = render_floor_svg(level, seed=7)
        assert "bush-canopy" in svg

"""Tests for site-level enclosure renderers (M6+).

See design/building_generator.md section 7.2 for the full spec.
M6 covers the fortification wall: continuous dark base stroke plus
an equally-spaced white dashed overlay, with gate gaps cutting the
polygon into sub-polylines.
"""

import math
import re

import pytest

from nhc.rendering._enclosures import (
    FORTIFICATION_CORNER_FILL,
    FORTIFICATION_CORNER_SCALE,
    FORTIFICATION_CORNER_STYLES,
    FORTIFICATION_CRENEL_FILL,
    FORTIFICATION_MERLON_FILL,
    FORTIFICATION_RATIO,
    FORTIFICATION_SIZE,
    FORTIFICATION_STROKE,
    FORTIFICATION_STROKE_WIDTH,
    PALISADE_CIRCLE_STEP,
    PALISADE_DOOR_LENGTH_PX,
    PALISADE_FILL,
    PALISADE_RADIUS_MAX,
    PALISADE_RADIUS_MIN,
    PALISADE_STROKE,
    render_fortification_enclosure,
    render_fortification_polyline,
    render_palisade_enclosure,
    render_palisade_polyline,
)


def _parse_rects(items: list[str]) -> list[dict]:
    """Parse each SVG <rect> string into a dict of attrs."""
    out = []
    for s in items:
        if "<rect" not in s:
            continue
        # Attribute names may contain hyphens (stroke-width), so
        # accept [\w-]+ rather than \w+.
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', s))
        out.append(attrs)
    return out


def _merlon_count(items: list[str]) -> int:
    return sum(
        1 for a in _parse_rects(items)
        if a.get("fill") == FORTIFICATION_MERLON_FILL
    )


def _crenel_count(items: list[str]) -> int:
    return sum(
        1 for a in _parse_rects(items)
        if a.get("fill") == FORTIFICATION_CRENEL_FILL
    )


class TestFortificationPolyline:
    def test_empty_points_returns_empty(self):
        assert render_fortification_polyline([]) == []
        assert render_fortification_polyline([(0.0, 0.0)]) == []

    def test_horizontal_run_emits_merlons_and_crenels(self):
        out = render_fortification_polyline([(0, 100), (200, 100)])
        assert _merlon_count(out) >= 5
        assert _crenel_count(out) >= 5

    def test_shapes_alternate_along_horizontal_run(self):
        out = render_fortification_polyline([(0, 100), (300, 100)])
        rects = _parse_rects(out)
        fills = [a["fill"] for a in rects]
        assert fills, "no rects emitted"
        # Strictly alternate: M, C, M, C, ...
        for i in range(len(fills) - 1):
            assert fills[i] != fills[i + 1], (
                f"non-alternating at index {i}: {fills[i]} then "
                f"{fills[i + 1]}"
            )

    def test_first_shape_is_merlon(self):
        out = render_fortification_polyline([(0, 100), (200, 100)])
        rects = _parse_rects(out)
        assert rects
        assert rects[0]["fill"] == FORTIFICATION_MERLON_FILL

    def test_horizontal_merlons_are_square(self):
        out = render_fortification_polyline([(0, 100), (200, 100)])
        for a in _parse_rects(out):
            if a["fill"] != FORTIFICATION_MERLON_FILL:
                continue
            assert math.isclose(float(a["width"]), FORTIFICATION_SIZE)
            assert math.isclose(float(a["height"]), FORTIFICATION_SIZE)

    def test_horizontal_crenels_use_din_a_ratio(self):
        """On a horizontal run the crenel is wider than tall by √2."""
        out = render_fortification_polyline([(0, 100), (200, 100)])
        for a in _parse_rects(out):
            if a["fill"] != FORTIFICATION_CRENEL_FILL:
                continue
            w = float(a["width"])
            h = float(a["height"])
            assert math.isclose(
                w / h, FORTIFICATION_RATIO, rel_tol=0.02,
            )

    def test_vertical_crenels_use_din_a_ratio(self):
        """On a vertical run the crenel is taller than wide by √2."""
        out = render_fortification_polyline([(100, 0), (100, 300)])
        crenels = [
            a for a in _parse_rects(out)
            if a["fill"] == FORTIFICATION_CRENEL_FILL
        ]
        assert crenels
        for a in crenels:
            w = float(a["width"])
            h = float(a["height"])
            assert math.isclose(
                h / w, FORTIFICATION_RATIO, rel_tol=0.02,
            )

    def test_all_shapes_share_thin_stroke(self):
        out = render_fortification_polyline([(0, 100), (200, 100)])
        rects = _parse_rects(out)
        assert rects
        for a in rects:
            assert a["stroke"] == FORTIFICATION_STROKE
            assert math.isclose(
                float(a["stroke-width"]),
                FORTIFICATION_STROKE_WIDTH,
            )

    def test_diagonal_segment_emits_nothing(self):
        """Non-orthogonal segments are skipped (building polygons
        are all axis-aligned)."""
        out = render_fortification_polyline([(0, 0), (100, 100)])
        assert out == []


class TestFortificationClosedEnclosure:
    def test_empty_polygon_returns_empty(self):
        assert render_fortification_enclosure([]) == []

    def test_rect_no_gates_emits_shapes_on_every_edge(self):
        polygon = [(0, 0), (200, 0), (200, 120), (0, 120)]
        out = render_fortification_enclosure(polygon)
        # 4 corners + alternating on edges.
        assert _merlon_count(out) >= 4 + 4
        assert _crenel_count(out) >= 8

    def test_rect_no_gates_uses_merlon_and_crenel_fills(self):
        polygon = [(0, 0), (200, 0), (200, 120), (0, 120)]
        out = render_fortification_enclosure(polygon)
        fills = {a["fill"] for a in _parse_rects(out)}
        assert FORTIFICATION_MERLON_FILL in fills
        assert FORTIFICATION_CRENEL_FILL in fills


def _centers_near(a: dict, polygon, tol: float = 0.5) -> bool:
    """True if rect ``a``'s centre lies at a polygon vertex."""
    cx = float(a["x"]) + float(a["width"]) / 2
    cy = float(a["y"]) + float(a["height"]) / 2
    for (vx, vy) in polygon:
        if (math.isclose(cx, vx, abs_tol=tol)
                and math.isclose(cy, vy, abs_tol=tol)):
            return True
    return False


class TestFortificationCornerShapes:
    def test_rect_emits_one_corner_per_vertex(self):
        """Black corner shapes sit exactly at each polygon vertex."""
        polygon = [(0, 0), (200, 0), (200, 120), (0, 120)]
        out = render_fortification_enclosure(polygon)
        rects = _parse_rects(out)
        found = 0
        for a in rects:
            if a["fill"] != FORTIFICATION_CORNER_FILL:
                continue
            if _centers_near(a, polygon):
                found += 1
        assert found == 4

    def test_corner_is_wider_than_wall_thickness(self):
        """Corners overlap the wall band by extending past SIZE."""
        polygon = [(0, 0), (200, 0), (200, 120), (0, 120)]
        out = render_fortification_enclosure(polygon)
        for a in _parse_rects(out):
            if not _centers_near(a, polygon):
                continue
            assert float(a["width"]) > FORTIFICATION_SIZE
            assert float(a["height"]) > FORTIFICATION_SIZE

    def test_corner_fill_is_black(self):
        assert FORTIFICATION_CORNER_FILL == "#000000"

    def test_first_edge_shape_is_crenel(self):
        """The corner carries the first black shape; the remaining
        edge pattern starts with a crenel."""
        polygon = [(0, 0), (200, 0), (200, 120), (0, 120)]
        out = render_fortification_enclosure(polygon)
        rects = _parse_rects(out)
        bottom = []
        for a in rects:
            cy = float(a["y"]) + float(a["height"]) / 2
            if not math.isclose(cy, 0, abs_tol=0.1):
                continue
            if _centers_near(a, polygon):
                continue
            bottom.append(a)
        bottom.sort(key=lambda a: float(a["x"]))
        assert bottom
        assert bottom[0]["fill"] == FORTIFICATION_CRENEL_FILL

    def test_edge_pattern_is_centered(self):
        """Leftover inset space is split evenly across the edge."""
        polygon = [(0, 0), (200, 0), (200, 120), (0, 120)]
        out = render_fortification_enclosure(polygon)
        rects = _parse_rects(out)
        bottom = []
        for a in rects:
            cy = float(a["y"]) + float(a["height"]) / 2
            if not math.isclose(cy, 0, abs_tol=0.1):
                continue
            if _centers_near(a, polygon):
                continue
            bottom.append(a)
        bottom.sort(key=lambda a: float(a["x"]))
        assert bottom
        # Inset is FORTIFICATION_SIZE/2 on each end.
        inset = FORTIFICATION_SIZE / 2
        left_gap = float(bottom[0]["x"]) - inset
        right_edge_x = (
            float(bottom[-1]["x"]) + float(bottom[-1]["width"])
        )
        right_gap = (200 - inset) - right_edge_x
        assert math.isclose(left_gap, right_gap, abs_tol=0.2), (
            f"pattern not centered: left={left_gap:.2f}, "
            f"right={right_gap:.2f}"
        )


class TestFortificationCornerStyles:
    def test_corner_styles_contains_two(self):
        assert set(FORTIFICATION_CORNER_STYLES) == {
            "merlon", "diamond",
        }

    def test_default_corner_style_is_merlon(self):
        polygon = [(0, 0), (200, 0), (200, 120), (0, 120)]
        default = render_fortification_enclosure(polygon)
        explicit = render_fortification_enclosure(
            polygon, corner_style="merlon",
        )
        assert default == explicit

    def test_merlon_corner_uses_corner_scale(self):
        polygon = [(0, 0), (200, 0), (200, 120), (0, 120)]
        out = render_fortification_enclosure(polygon)
        expected = FORTIFICATION_SIZE * FORTIFICATION_CORNER_SCALE
        corners = 0
        for a in _parse_rects(out):
            if not _centers_near(a, polygon):
                continue
            w = float(a["width"])
            h = float(a["height"])
            if math.isclose(w, expected) and math.isclose(h, expected):
                corners += 1
        assert corners == 4

    def test_diamond_style_corners_carry_rotation(self):
        polygon = [(0, 0), (200, 0), (200, 120), (0, 120)]
        out = render_fortification_enclosure(
            polygon, corner_style="diamond",
        )
        rotated = [
            s for s in out
            if "<rect" in s and "rotate(45" in s
        ]
        assert len(rotated) == 4

    def test_diamond_corners_use_corner_fill(self):
        polygon = [(0, 0), (200, 0), (200, 120), (0, 120)]
        out = render_fortification_enclosure(
            polygon, corner_style="diamond",
        )
        rotated = [s for s in out if "rotate(45" in s]
        for s in rotated:
            assert f'fill="{FORTIFICATION_CORNER_FILL}"' in s

    def test_invalid_corner_style_raises(self):
        polygon = [(0, 0), (200, 0), (200, 120), (0, 120)]
        with pytest.raises(ValueError):
            render_fortification_enclosure(
                polygon, corner_style="tower",
            )


class TestFortificationMerlonGrey:
    def test_merlon_fill_is_soft_grey_not_white(self):
        assert FORTIFICATION_MERLON_FILL != "#FFFFFF"
        # A soft grey has equal R, G, B channels in a mid-light range.
        hx = FORTIFICATION_MERLON_FILL.lstrip("#")
        r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
        assert r == g == b
        assert 160 < r < 240


class TestFortificationGateGap:
    def test_gate_reduces_shape_count(self):
        polygon = [(0, 0), (200, 0), (200, 120), (0, 120)]
        baseline = render_fortification_enclosure(polygon)
        gated = render_fortification_enclosure(
            polygon, gates=[(0, 0.5, 30.0)],
        )
        assert len(gated) < len(baseline)

    def test_two_gates_reduce_more(self):
        polygon = [(0, 0), (200, 0), (200, 120), (0, 120)]
        baseline = render_fortification_enclosure(polygon)
        one = render_fortification_enclosure(
            polygon, gates=[(0, 0.5, 30.0)],
        )
        two = render_fortification_enclosure(
            polygon,
            gates=[(0, 0.5, 30.0), (2, 0.5, 30.0)],
        )
        assert len(two) < len(one) < len(baseline)

    def test_gate_endpoints_inside_edge(self):
        polygon = [(0, 0), (200, 0), (200, 120), (0, 120)]
        gates = [(0, 0.05, 60.0)]  # clamped
        out = render_fortification_enclosure(polygon, gates=gates)
        assert out

    def test_gate_on_invalid_edge_index_falls_back(self):
        polygon = [(0, 0), (200, 0), (200, 120), (0, 120)]
        gates = [(99, 0.5, 10.0)]
        baseline = render_fortification_enclosure(polygon)
        out = render_fortification_enclosure(polygon, gates=gates)
        # Invalid gate is rejected and we fall back to gate-less
        # render, so counts match.
        assert len(out) == len(baseline)


class TestFortificationPalette:
    def test_crenel_fill_is_black(self):
        assert FORTIFICATION_CRENEL_FILL == "#000000"

    def test_stroke_color_is_dark(self):
        assert FORTIFICATION_STROKE == "#1A1A1A"

    def test_stroke_is_thin(self):
        assert 0 < FORTIFICATION_STROKE_WIDTH <= 1.5

    def test_size_positive(self):
        assert FORTIFICATION_SIZE > 0

    def test_ratio_is_din_a(self):
        assert math.isclose(
            FORTIFICATION_RATIO, math.sqrt(2), rel_tol=1e-9,
        )


def _circles(items: list[str]) -> list[str]:
    return [s for s in items if s.lstrip().startswith("<circle ")]


def _rects(items: list[str]) -> list[str]:
    return [s for s in items if s.lstrip().startswith("<rect ")]


class TestPalisadePolyline:
    def test_empty_points_returns_empty(self):
        assert render_palisade_polyline([]) == []
        assert render_palisade_polyline([(0.0, 0.0)]) == []

    def test_polyline_emits_circles(self):
        out = render_palisade_polyline([(0, 0), (100, 0)], seed=1)
        circles = _circles(out)
        # Step is ``2 * max_effective_radius + gap`` so adjacent
        # circles never overlap; count is smaller than the dense
        # original but still a handful on a 100px segment.
        assert len(circles) > 5

    def test_circle_uses_palisade_palette(self):
        out = render_palisade_polyline([(0, 0), (100, 0)], seed=1)
        circles = _circles(out)
        for c in circles:
            assert f'fill="{PALISADE_FILL}"' in c
            assert f'stroke="{PALISADE_STROKE}"' in c

    def test_circle_radius_within_bounds(self):
        out = render_palisade_polyline([(0, 0), (200, 0)], seed=3)
        circles = _circles(out)
        assert circles
        for c in circles:
            m = re.search(r'r="([0-9.]+)"', c)
            assert m
            r = float(m.group(1))
            # Allow ±0.3 jitter beyond the bounds (doc says
            # "±0.3px jitter per circle").
            assert PALISADE_RADIUS_MIN - 0.31 <= r
            assert r <= PALISADE_RADIUS_MAX + 0.31

    def test_adjacent_circles_do_not_overlap(self):
        """Distance between adjacent circle centres is >= sum of radii."""
        out = render_palisade_polyline([(0, 0), (300, 0)], seed=5)
        parsed: list[tuple[float, float, float]] = []
        for c in _circles(out):
            mx = re.search(r'cx="([0-9.]+)"', c)
            my = re.search(r'cy="([0-9.]+)"', c)
            mr = re.search(r'r="([0-9.]+)"', c)
            assert mx and my and mr
            parsed.append(
                (float(mx.group(1)), float(my.group(1)),
                 float(mr.group(1))),
            )
        assert len(parsed) >= 2
        for (x0, y0, r0), (x1, y1, r1) in zip(parsed, parsed[1:]):
            dist = ((x0 - x1) ** 2 + (y0 - y1) ** 2) ** 0.5
            assert dist >= r0 + r1 - 1e-6, (
                f"circles at ({x0},{y0}) r={r0} and "
                f"({x1},{y1}) r={r1} overlap (dist={dist:.2f})"
            )


class TestPalisadeDeterminism:
    def test_same_seed_same_output(self):
        a = render_palisade_polyline([(0, 0), (200, 0)], seed=7)
        b = render_palisade_polyline([(0, 0), (200, 0)], seed=7)
        assert a == b

    def test_different_seed_differs(self):
        a = render_palisade_polyline([(0, 0), (200, 0)], seed=1)
        b = render_palisade_polyline([(0, 0), (200, 0)], seed=2)
        assert a != b


class TestPalisadeEnclosure:
    def test_closed_polygon_no_gates_emits_circles(self):
        polygon = [(0, 0), (100, 0), (100, 50), (0, 50)]
        out = render_palisade_enclosure(polygon, seed=1)
        assert len(_circles(out)) > 20
        # No rectangles when there are no gates.
        assert _rects(out) == []

    def test_gate_inserts_rectangle(self):
        polygon = [(0, 0), (100, 0), (100, 50), (0, 50)]
        gates = [(0, 0.5, PALISADE_DOOR_LENGTH_PX / 2)]
        out = render_palisade_enclosure(polygon, gates=gates, seed=1)
        rects = _rects(out)
        # Exactly one door rect per gate.
        assert len(rects) == 1
        rect = rects[0]
        assert f'fill="{PALISADE_FILL}"' in rect
        assert f'stroke="{PALISADE_STROKE}"' in rect

    def test_gate_rectangle_matches_door_length(self):
        polygon = [(0, 0), (200, 0), (200, 50), (0, 50)]
        gates = [(0, 0.5, PALISADE_DOOR_LENGTH_PX / 2)]
        out = render_palisade_enclosure(polygon, gates=gates, seed=1)
        rect = _rects(out)[0]
        m_w = re.search(r'width="([0-9.]+)"', rect)
        assert m_w
        # Door span = 2 * half-len.
        assert (
            abs(float(m_w.group(1)) - PALISADE_DOOR_LENGTH_PX) < 0.5
        )

    def test_gate_removes_circles_from_gap(self):
        polygon = [(0, 0), (200, 0), (200, 50), (0, 50)]
        no_gates = render_palisade_enclosure(polygon, seed=1)
        with_gate = render_palisade_enclosure(
            polygon,
            gates=[(0, 0.5, PALISADE_DOOR_LENGTH_PX / 2)],
            seed=1,
        )
        assert len(_circles(with_gate)) < len(_circles(no_gates))

    def test_two_gates_two_rectangles(self):
        polygon = [(0, 0), (200, 0), (200, 50), (0, 50)]
        gates = [
            (0, 0.5, PALISADE_DOOR_LENGTH_PX / 2),
            (2, 0.5, PALISADE_DOOR_LENGTH_PX / 2),
        ]
        out = render_palisade_enclosure(polygon, gates=gates, seed=1)
        assert len(_rects(out)) == 2


class TestPalisadePalette:
    def test_fill_is_soft_brown(self):
        assert PALISADE_FILL == "#8A5A2A"

    def test_stroke_is_dark_brown(self):
        assert PALISADE_STROKE == "#4A2E1A"

    def test_radius_bounds_match_spec(self):
        assert PALISADE_RADIUS_MIN == 3.0
        assert PALISADE_RADIUS_MAX == 4.0

    def test_step_is_positive(self):
        assert PALISADE_CIRCLE_STEP > 0

    def test_door_length_positive(self):
        assert PALISADE_DOOR_LENGTH_PX > 0

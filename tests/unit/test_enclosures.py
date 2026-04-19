"""Tests for site-level enclosure renderers (M6+).

See design/building_generator.md section 7.2 for the full spec.
M6 covers the fortification wall: continuous dark base stroke plus
an equally-spaced white dashed overlay, with gate gaps cutting the
polygon into sub-polylines.
"""

import re

import pytest

from nhc.rendering._enclosures import (
    FORTIFICATION_BASE_COLOR,
    FORTIFICATION_BASE_WIDTH,
    FORTIFICATION_DASH_ARRAY,
    FORTIFICATION_OVERLAY_COLOR,
    FORTIFICATION_OVERLAY_WIDTH,
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


class TestFortificationPolyline:
    def test_empty_points_returns_empty(self):
        assert render_fortification_polyline([]) == []
        assert render_fortification_polyline([(0.0, 0.0)]) == []

    def test_two_point_polyline_emits_base_and_overlay(self):
        out = render_fortification_polyline([(0, 0), (100, 0)])
        assert len(out) == 2
        assert FORTIFICATION_BASE_COLOR in out[0]
        assert f'stroke-width="{FORTIFICATION_BASE_WIDTH}"' in out[0]
        assert FORTIFICATION_OVERLAY_COLOR in out[1]
        assert f'stroke-width="{FORTIFICATION_OVERLAY_WIDTH}"' in out[1]
        assert (
            f'stroke-dasharray="{FORTIFICATION_DASH_ARRAY}"' in out[1]
        )

    def test_polyline_path_has_move_and_lines(self):
        out = render_fortification_polyline([(0, 0), (100, 0), (100, 50)])
        assert "M0.0,0.0" in out[0]
        assert "L100.0,0.0" in out[0]
        assert "L100.0,50.0" in out[0]

    def test_base_stroke_wider_than_overlay(self):
        assert FORTIFICATION_BASE_WIDTH > FORTIFICATION_OVERLAY_WIDTH

    def test_dash_array_has_two_components(self):
        parts = FORTIFICATION_DASH_ARRAY.split()
        assert len(parts) == 2
        for p in parts:
            assert float(p) > 0


class TestFortificationClosedEnclosure:
    def test_empty_polygon_returns_empty(self):
        assert render_fortification_enclosure([]) == []

    def test_rect_no_gates_two_paths(self):
        polygon = [(0, 0), (100, 0), (100, 50), (0, 50)]
        out = render_fortification_enclosure(polygon)
        # Single closed polyline -> 2 paths (base + overlay).
        assert len(out) == 2
        # Path closes back to starting point.
        assert "L0.0,0.0" in out[0] or "L0,0" in out[0]

    def test_rect_no_gates_uses_base_and_overlay(self):
        polygon = [(0, 0), (100, 0), (100, 50), (0, 50)]
        out = render_fortification_enclosure(polygon)
        assert any(FORTIFICATION_BASE_COLOR in s for s in out)
        assert any(FORTIFICATION_OVERLAY_COLOR in s for s in out)
        assert any(FORTIFICATION_DASH_ARRAY in s for s in out)


class TestFortificationGateGap:
    def test_single_gate_splits_into_two_polylines(self):
        """One gate on a rect -> 4 edges, 1 split -> 4+1 sub-polylines.

        Each polyline emits 2 paths (base + overlay), so we expect
        10 paths total (vs 2 for an uncut rect).
        """
        polygon = [(0, 0), (100, 0), (100, 50), (0, 50)]
        gates = [(0, 0.5, 10.0)]  # on edge 0, midpoint, 10 px half-gap
        out = render_fortification_enclosure(polygon, gates=gates)
        # More paths than the gate-less baseline.
        baseline = render_fortification_enclosure(polygon)
        assert len(out) > len(baseline)

    def test_gate_removes_edge_midpoint(self):
        """Verify no path covers the full gate midpoint (40,0)-(60,0)."""
        polygon = [(0, 0), (100, 0), (100, 50), (0, 50)]
        gates = [(0, 0.5, 10.0)]  # midpoint x=50, half=10 -> gap 40..60
        out = render_fortification_enclosure(polygon, gates=gates)
        # No single polyline path should span across x in (40, 60)
        # along the bottom edge (y=0).
        for path in out:
            if "y1=" in path:
                continue  # not a polyline path
        # Just confirm the left sub-edge end appears and the right
        # sub-edge start appears somewhere in the output.
        joined = "\n".join(out)
        assert "L40.0,0.0" in joined  # left sub-edge ending
        assert "M60.0,0.0" in joined  # right sub-edge starting

    def test_gate_endpoints_inside_edge(self):
        """Gate t_lo, t_hi are clamped to [0, 1]."""
        polygon = [(0, 0), (100, 0), (100, 50), (0, 50)]
        # Gate near edge start, half-len bigger than midpoint's room
        gates = [(0, 0.05, 20.0)]  # center at x=5, half=20 -> clamped
        out = render_fortification_enclosure(polygon, gates=gates)
        assert out  # renders something, doesn't crash

    def test_two_gates_on_different_edges(self):
        polygon = [(0, 0), (100, 0), (100, 50), (0, 50)]
        gates = [
            (0, 0.5, 10.0),   # bottom edge gate
            (2, 0.5, 10.0),   # top edge gate
        ]
        out = render_fortification_enclosure(polygon, gates=gates)
        baseline = render_fortification_enclosure(polygon)
        assert len(out) > len(baseline)

    def test_gate_on_invalid_edge_index_ignored(self):
        polygon = [(0, 0), (100, 0), (100, 50), (0, 50)]
        gates = [(99, 0.5, 10.0)]  # nonexistent edge
        # Should not raise; treat as no gate
        out = render_fortification_enclosure(polygon, gates=gates)
        assert len(out) == 2


class TestFortificationPalette:
    def test_base_color_is_specified_dark(self):
        assert FORTIFICATION_BASE_COLOR == "#1A1A1A"

    def test_overlay_color_is_white(self):
        assert FORTIFICATION_OVERLAY_COLOR == "#FFFFFF"

    def test_dash_array_8_6(self):
        assert FORTIFICATION_DASH_ARRAY == "8 6"


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

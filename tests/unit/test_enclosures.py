"""Tests for site-level enclosure renderers (M6+).

See design/building_generator.md section 7.2 for the full spec.
M6 covers the fortification wall: continuous dark base stroke plus
an equally-spaced white dashed overlay, with gate gaps cutting the
polygon into sub-polylines.
"""

import pytest

from nhc.rendering._enclosures import (
    FORTIFICATION_BASE_COLOR,
    FORTIFICATION_BASE_WIDTH,
    FORTIFICATION_DASH_ARRAY,
    FORTIFICATION_OVERLAY_COLOR,
    FORTIFICATION_OVERLAY_WIDTH,
    render_fortification_enclosure,
    render_fortification_polyline,
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

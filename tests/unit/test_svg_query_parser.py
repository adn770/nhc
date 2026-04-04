"""Tests for the MCP SVG query path parser — must handle the
cubic bezier (C) commands used by cave wall outlines."""

from __future__ import annotations

from nhc.debug_tools.tools.svg_query import (
    _parse_path_segments, _segment_overlaps_tile,
)


class TestParsePathSegments:
    def test_parses_m_l_segments(self):
        d = "M100,200 L150,250 L200,300"
        segs = _parse_path_segments(d)
        assert (100.0, 200.0, 150.0, 250.0) in segs
        assert (150.0, 250.0, 200.0, 300.0) in segs

    def test_parses_cubic_bezier_as_line_segments(self):
        """A single cubic bezier from (0,0) to (32,0) should
        yield multiple sampled line segments for overlap tests."""
        d = "M0,0 C10,10 20,-10 32,0"
        segs = _parse_path_segments(d)
        assert len(segs) >= 2, (
            f"Bezier should be sampled, got {len(segs)} segments"
        )
        # First sampled segment starts at (0, 0)
        assert segs[0][0] == 0.0 and segs[0][1] == 0.0
        # Last sampled segment ends at (32, 0)
        assert segs[-1][2] == 32.0 and segs[-1][3] == 0.0

    def test_multiple_beziers_chained(self):
        """M followed by multiple C commands."""
        d = "M0,0 C5,5 10,5 15,0 C20,-5 25,-5 30,0"
        segs = _parse_path_segments(d)
        assert len(segs) >= 4
        # Full chain: starts at (0,0), ends at (30,0)
        assert segs[0][0] == 0.0
        assert segs[-1][2] == 30.0

    def test_bezier_point_detection_in_tile(self):
        """A bezier curve passing through a tile should be
        detected by _segment_overlaps_tile via the sampled
        line segments."""
        # Curve from (0, 100) arcing through (100, 100)
        d = "M0,100 C50,80 50,80 100,100"
        segs = _parse_path_segments(d)
        # Tile at (64, 64) size 32: the curve passes through it
        tile_hit = any(
            _segment_overlaps_tile(*s, 64, 64, 32, 32)
            for s in segs
        )
        assert tile_hit, (
            "Sampled bezier segments should detect tile overlap"
        )

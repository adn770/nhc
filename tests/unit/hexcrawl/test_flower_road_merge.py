"""Tests for structural merging of road segments within a flower.

When a macro hex has two ``path`` EdgeSegments exiting via the same
edge, their sub-hex routes must share a trunk toward that exit
instead of running as two parallel paths across the flower. The
later-routed road becomes a branch that terminates at the junction
sub-cell (``exit_macro_edge=None``).
"""

from __future__ import annotations

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl._flowers import generate_flower
from nhc.hexcrawl.model import (
    Biome,
    EdgeSegment,
    HexCell,
    HexFeatureType,
)


def _make_cell(edges: list[EdgeSegment]) -> HexCell:
    return HexCell(
        coord=HexCoord(0, 0),
        biome=Biome.GREENLANDS,
        feature=HexFeatureType.NONE,
        elevation=0.3,
        edges=list(edges),
    )


def test_two_roads_same_exit_share_interior_cell() -> None:
    """Two roads with the same exit edge but different entries must
    share at least one sub-cell besides the exit-boundary cell."""
    parent = _make_cell([
        EdgeSegment(type="path", entry_edge=0, exit_edge=3),
        EdgeSegment(type="path", entry_edge=1, exit_edge=3),
    ])
    flower = generate_flower(parent, {parent.coord: parent}, seed=42)
    road_segs = [e for e in flower.edges if e.type == "path"]
    assert len(road_segs) == 2
    shared = set(road_segs[0].path) & set(road_segs[1].path)
    assert shared, "two roads to the same exit must share trunk cells"


def test_later_road_is_trimmed_to_junction() -> None:
    """The later-routed road becomes a branch: its path terminates
    at a cell belonging to the earlier trunk, and
    ``exit_macro_edge`` is ``None`` to mark it as a sink."""
    parent = _make_cell([
        EdgeSegment(type="path", entry_edge=0, exit_edge=3),
        EdgeSegment(type="path", entry_edge=1, exit_edge=3),
    ])
    flower = generate_flower(parent, {parent.coord: parent}, seed=42)
    road_segs = [e for e in flower.edges if e.type == "path"]
    trunk, branch = road_segs[0], road_segs[1]
    assert trunk.exit_macro_edge == 3, "first routed road keeps its exit"
    assert branch.exit_macro_edge is None, (
        "branch terminates at junction, exit_macro_edge must be None"
    )
    assert branch.entry_macro_edge == 1
    assert branch.path[-1] in set(trunk.path), (
        "branch's final cell must be a sub-cell of the trunk"
    )


def test_two_roads_different_exits_are_not_merged() -> None:
    """Roads that exit via different edges must remain independent
    full paths. Neither gets trimmed."""
    parent = _make_cell([
        EdgeSegment(type="path", entry_edge=0, exit_edge=3),
        EdgeSegment(type="path", entry_edge=1, exit_edge=4),
    ])
    flower = generate_flower(parent, {parent.coord: parent}, seed=42)
    road_segs = [e for e in flower.edges if e.type == "path"]
    assert len(road_segs) == 2
    exits = sorted(e.exit_macro_edge for e in road_segs)
    assert exits == [3, 4]


def test_single_road_unaffected() -> None:
    """A flower with one path segment still produces a full segment
    (entry and exit both set)."""
    parent = _make_cell([
        EdgeSegment(type="path", entry_edge=0, exit_edge=3),
    ])
    flower = generate_flower(parent, {parent.coord: parent}, seed=42)
    road_segs = [e for e in flower.edges if e.type == "path"]
    assert len(road_segs) == 1
    assert road_segs[0].entry_macro_edge == 0
    assert road_segs[0].exit_macro_edge == 3


def test_terminus_roads_not_forced_to_merge() -> None:
    """Roads that terminate in the hex (exit_edge=None) are routed
    independently and never get trimmed."""
    parent = HexCell(
        coord=HexCoord(0, 0),
        biome=Biome.GREENLANDS,
        feature=HexFeatureType.VILLAGE,
        elevation=0.3,
        edges=[
            EdgeSegment(type="path", entry_edge=0, exit_edge=None),
            EdgeSegment(type="path", entry_edge=3, exit_edge=None),
        ],
    )
    flower = generate_flower(parent, {parent.coord: parent}, seed=42)
    road_segs = [e for e in flower.edges if e.type == "path"]
    assert len(road_segs) == 2
    # Both remain terminus segments; no forced trim based on exit.
    for seg in road_segs:
        assert seg.exit_macro_edge is None

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


def test_two_roads_same_exit_share_trunk_or_absorbed() -> None:
    """Two roads with the same exit edge either share the trunk
    cells via an anchor (the later road is trimmed to a branch
    that terminates at a trunk cell) or, when the A* bias places
    the later road entirely on the existing trunk, the later
    segment is absorbed so no sub-cell is drawn twice."""
    parent = _make_cell([
        EdgeSegment(type="path", entry_edge=0, exit_edge=3),
        EdgeSegment(type="path", entry_edge=1, exit_edge=3),
    ])
    flower = generate_flower(parent, {parent.coord: parent}, seed=42)
    road_segs = [e for e in flower.edges if e.type == "path"]
    assert len(road_segs) in (1, 2)
    if len(road_segs) == 2:
        trunk, branch = road_segs[0], road_segs[1]
        assert branch.path[-1] in set(trunk.path), (
            "branch must terminate at a cell of the trunk"
        )


def test_later_road_is_trimmed_when_paths_partially_overlap() -> None:
    """Across a spread of seeds, for a 2-segment same-exit setup
    the invariants hold: either one segment is absorbed, the
    paths end at the same sub-cell (trivial "share"), or the
    later segment is trimmed so its last cell is a trunk cell.
    The ``exit_macro_edge`` becomes ``None`` in the trimmed
    case."""
    kept = 0
    for seed in range(40):
        parent = _make_cell([
            EdgeSegment(type="path", entry_edge=0, exit_edge=3),
            EdgeSegment(type="path", entry_edge=2, exit_edge=3),
        ])
        flower = generate_flower(
            parent, {parent.coord: parent}, seed=seed,
        )
        road_segs = [e for e in flower.edges if e.type == "path"]
        if len(road_segs) != 2:
            continue
        trunk, branch = road_segs[0], road_segs[1]
        assert trunk.exit_macro_edge == 3
        # Either branch fully reaches its own exit (paths diverge;
        # nothing to trim) or it was trimmed to end on the trunk.
        if branch.exit_macro_edge is None:
            assert branch.path[-1] in set(trunk.path), (
                "trimmed branch's last cell must land on trunk"
            )
            kept += 1
    assert kept > 0, (
        "no seed in 40 produced a partial-overlap trim; trim "
        "path may never be exercised"
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


def test_hub_source_sink_segments_share_at_most_an_anchor_cell() -> None:
    """Multiple source / sink segments converging on the same
    feature cell (a hub) should not each draw the same trunk
    sub-cells. The renderer draws each segment's full sub_path,
    so without merging the inner cells of a shared trunk
    (feature-cell-adjacent) get stamped two or three times --
    the "doubled road near the town" look seen in the live
    session. After the fix any cell that appears in two
    segments is the anchor where one branches off the other;
    cells cannot appear in three or more segments."""
    parent = HexCell(
        coord=HexCoord(0, 0),
        biome=Biome.GREENLANDS,
        feature=HexFeatureType.VILLAGE,
        elevation=0.3,
        edges=[
            EdgeSegment(type="path", entry_edge=3, exit_edge=None),
            EdgeSegment(type="path", entry_edge=None, exit_edge=2),
            EdgeSegment(type="path", entry_edge=None, exit_edge=5),
        ],
    )
    flower = generate_flower(parent, {parent.coord: parent}, seed=42)
    road_segs = [e for e in flower.edges if e.type == "path"]
    assert 1 <= len(road_segs) <= 3
    from collections import Counter
    counts = Counter(
        cell for seg in road_segs for cell in seg.path
    )
    for cell, n in counts.items():
        assert n <= 2, (
            f"cell {cell} appears in {n} road segments; at most "
            "two are allowed (branch + trunk at the anchor)"
        )


def test_hub_branch_trims_from_start_not_end() -> None:
    """A source segment that leaves the hub toward an edge should
    have its opening trunk cells (those overlapping an earlier
    segment's path) trimmed from the START. The remaining
    sub-path anchors at the last shared cell with the trunk and
    walks outward to the edge."""
    parent = HexCell(
        coord=HexCoord(0, 0),
        biome=Biome.GREENLANDS,
        feature=HexFeatureType.VILLAGE,
        elevation=0.3,
        edges=[
            EdgeSegment(type="path", entry_edge=3, exit_edge=None),
            EdgeSegment(type="path", entry_edge=None, exit_edge=2),
            EdgeSegment(type="path", entry_edge=None, exit_edge=5),
        ],
    )
    flower = generate_flower(parent, {parent.coord: parent}, seed=42)
    road_segs = [e for e in flower.edges if e.type == "path"]
    first = road_segs[0]
    first_cells = set(first.path)
    for seg in road_segs[1:]:
        # If the segment's original path overlaps `first` by 2+
        # cells at the beginning, it must be trimmed so only the
        # anchor (last shared cell) remains in the overlap. An
        # entry trimmed from the start also loses its entry
        # edge -- the branch now starts interior.
        if seg.entry_macro_edge is None and seg.path[0] in first_cells:
            # Trimmed source: subsequent cells must be disjoint.
            assert all(
                c not in first_cells
                for c in seg.path[1:]
            ), (
                f"segment entry={seg.entry_macro_edge} "
                f"exit={seg.exit_macro_edge} still overlaps the "
                "trunk beyond its anchor cell"
            )

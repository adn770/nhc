"""Tests for structural merging of river segments within a flower.

Mirrors :mod:`test_flower_road_merge` for rivers. When a macro hex
has two ``river`` EdgeSegments that share a macro edge (two rivers
flowing to the sea via the same exit, or two tributaries joining
at a confluence before exiting), their sub-hex routes must share
a trunk toward the shared edge instead of running as two parallel
paths across the flower. The later-routed river becomes a branch
that terminates on the trunk at the junction sub-cell.
"""

from __future__ import annotations

from collections import Counter

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


def test_two_rivers_same_exit_share_trunk_or_absorbed() -> None:
    """Two rivers with the same exit edge either share a trunk
    (the later river is trimmed to a branch that terminates on
    a trunk cell) or, when A* bias absorbs the later river
    entirely, only one segment remains."""
    parent = _make_cell([
        EdgeSegment(type="river", entry_edge=0, exit_edge=3),
        EdgeSegment(type="river", entry_edge=1, exit_edge=3),
    ])
    flower = generate_flower(
        parent, {parent.coord: parent}, seed=42,
    )
    river_segs = [e for e in flower.edges if e.type == "river"]
    assert len(river_segs) in (1, 2)
    if len(river_segs) == 2:
        trunk, branch = river_segs[0], river_segs[1]
        assert branch.path[-1] in set(trunk.path), (
            "branch must terminate at a cell of the trunk"
        )


def test_later_river_is_trimmed_when_paths_partially_overlap() -> None:
    kept = 0
    for seed in range(40):
        parent = _make_cell([
            EdgeSegment(type="river", entry_edge=0, exit_edge=3),
            EdgeSegment(type="river", entry_edge=2, exit_edge=3),
        ])
        flower = generate_flower(
            parent, {parent.coord: parent}, seed=seed,
        )
        river_segs = [e for e in flower.edges if e.type == "river"]
        if len(river_segs) != 2:
            continue
        trunk, branch = river_segs[0], river_segs[1]
        assert trunk.exit_macro_edge == 3
        if branch.exit_macro_edge is None:
            assert branch.path[-1] in set(trunk.path), (
                "trimmed branch's last cell must land on trunk"
            )
            kept += 1
    assert kept > 0, (
        "no seed in 40 produced a partial-overlap trim; river "
        "trim path may never be exercised"
    )


def test_two_rivers_different_exits_are_not_merged() -> None:
    """Rivers that exit via different edges must remain
    independent full paths."""
    parent = _make_cell([
        EdgeSegment(type="river", entry_edge=0, exit_edge=3),
        EdgeSegment(type="river", entry_edge=1, exit_edge=4),
    ])
    flower = generate_flower(
        parent, {parent.coord: parent}, seed=42,
    )
    river_segs = [e for e in flower.edges if e.type == "river"]
    assert len(river_segs) == 2
    exits = sorted(e.exit_macro_edge for e in river_segs)
    assert exits == [3, 4]


def test_single_river_unaffected() -> None:
    parent = _make_cell([
        EdgeSegment(type="river", entry_edge=0, exit_edge=3),
    ])
    flower = generate_flower(
        parent, {parent.coord: parent}, seed=42,
    )
    river_segs = [e for e in flower.edges if e.type == "river"]
    assert len(river_segs) == 1
    assert river_segs[0].entry_macro_edge == 0
    assert river_segs[0].exit_macro_edge == 3


def test_source_and_through_river_share_at_most_anchor() -> None:
    """The live session showed two rivers touching the same hex:
    one passing through (entry + exit) and another starting at
    the hex (source, no entry). Both reach the centre area; the
    renderer draws both, producing visual doubling. After the
    merge pass, any shared sub-cell must appear in at most two
    segments (the anchor on the branch's end)."""
    parent = _make_cell([
        EdgeSegment(type="river", entry_edge=3, exit_edge=1),
        EdgeSegment(type="river", entry_edge=None, exit_edge=0),
    ])
    flower = generate_flower(
        parent, {parent.coord: parent}, seed=42,
    )
    river_segs = [e for e in flower.edges if e.type == "river"]
    assert 1 <= len(river_segs) <= 2
    counts = Counter(
        cell for seg in river_segs for cell in seg.path
    )
    for cell, n in counts.items():
        assert n <= 2, (
            f"cell {cell} appears in {n} river segments; at most "
            "two are allowed (branch + trunk at the anchor)"
        )


def test_river_branch_trims_from_start_or_end() -> None:
    """A second river overlapping the first must be trimmed so
    its body is disjoint from the trunk except at one anchor."""
    parent = _make_cell([
        EdgeSegment(type="river", entry_edge=0, exit_edge=3),
        EdgeSegment(type="river", entry_edge=1, exit_edge=3),
    ])
    flower = generate_flower(
        parent, {parent.coord: parent}, seed=42,
    )
    river_segs = [e for e in flower.edges if e.type == "river"]
    if len(river_segs) < 2:
        return
    trunk_cells = set(river_segs[0].path)
    for seg in river_segs[1:]:
        overlap = [c for c in seg.path if c in trunk_cells]
        assert len(overlap) <= 1, (
            f"branch overlaps trunk on {len(overlap)} cells; "
            "expected a single anchor cell"
        )

"""Shared edge-segment stamping for rivers and roads.

Stamps :class:`~nhc.hexcrawl.model.EdgeSegment` entries along
a hex path so the renderer can draw continuous lines crossing
hex edges.
"""

from __future__ import annotations

from nhc.hexcrawl.coords import HexCoord, direction_index
from nhc.hexcrawl.model import EdgeSegment, HexCell


def stamp_edge_path(
    path: list[HexCoord],
    cells: dict[HexCoord, HexCell],
    segment_type: str,
    *,
    check_duplicates: bool = False,
) -> None:
    """Add ``EdgeSegment`` entries to each cell along *path*.

    Parameters
    ----------
    segment_type
        ``"river"`` or ``"path"``.
    check_duplicates
        When True, skip hexes that already carry a segment with
        the same or reversed (entry, exit) pair. Used by roads
        to prevent duplicate stamps when two A* paths share the
        same stretch.
    """
    for i, coord in enumerate(path):
        if i == 0:
            entry: int | None = None
        else:
            d = direction_index(path[i - 1], coord)
            entry = (d + 3) % 6

        if i == len(path) - 1:
            exit_: int | None = None
        else:
            exit_ = direction_index(coord, path[i + 1])

        if check_duplicates:
            duplicate = False
            for seg in cells[coord].edges:
                if seg.type != segment_type:
                    continue
                if (seg.entry_edge == entry
                        and seg.exit_edge == exit_):
                    duplicate = True
                    break
                if (seg.entry_edge == exit_
                        and seg.exit_edge == entry):
                    duplicate = True
                    break
            if duplicate:
                continue

        cells[coord].edges.append(
            EdgeSegment(
                type=segment_type,
                entry_edge=entry,
                exit_edge=exit_,
            ),
        )

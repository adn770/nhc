"""Palisade gates render with both gate rows filled by STREET.

Gates store ``(gx, gy, length)`` with ``length == 2``, so each
gate occupies a 2-tile span at ``(gx, gy)`` and ``(gx, gy+1)`` on
the wall normal. The spine router routes a single anchor
``(inner_gx, gy)`` (the top tile of the gate, one step inside);
``_widen_path`` thickens the path by one perpendicular tile.

Pre-fix the perpendicular widening always added one fixed
direction (``(x, y+1)`` for horizontal segments, ``(x+1, y)`` for
vertical). When the spine approached an east-side gate from the
north, the vertical widening tried ``(x+1, y)`` — outside the
palisade walkable bbox (``max_x`` is exclusive) — so the second
gate row stayed un-streeted. The visual: a 2-tile gate opening
with only its top half painted as street, the road appearing
"one tile off" from the gate centre.

The fix lets ``_widen_path`` fall back to the opposite
perpendicular when the primary side is unwalkable. These tests
pin the corrected fill: both rows of every palisade gate carry
STREET, regardless of approach direction.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import SurfaceType
from nhc.sites.town import assemble_town


def _street_tile(site, x: int, y: int) -> bool:
    if not site.surface.in_bounds(x, y):
        return False
    return site.surface.tiles[y][x].surface_type is SurfaceType.STREET


def _gate_anchor_inside(
    enclosure, gate: tuple[int, int, int],
) -> tuple[int, int]:
    """Return the walkable-side tile coords for a gate.

    Mirrors ``_gate_anchor`` in ``nhc/sites/_town_streets.py``: gates
    on the left wall (gx == min_x) anchor to (gx, gy); gates on the
    right wall (gx == max_x) anchor to (gx-1, gy). Gate length 2
    extends from gy to gy+1.
    """
    xs = [p[0] for p in enclosure.polygon]
    min_x, max_x = min(xs), max(xs)
    gx, gy, _ = gate
    if gx == min_x:
        return (gx, gy)
    if gx == max_x:
        return (gx - 1, gy)
    return (gx, gy)


class TestPalisadeGateStreetFillsBothRows:
    """For every settlement size that ships a palisade, every gate
    must have BOTH of its rows (length=2) rendered as STREET on the
    walkable side. Pin across enough seeds to catch direction-
    asymmetric routing bugs."""

    def test_city_gates_fill_both_rows_across_seeds(self) -> None:
        for seed in range(20):
            site = assemble_town(
                f"city_seed{seed}", random.Random(seed),
                size_class="city",
            )
            assert site.enclosure is not None, "city must have palisade"
            for gate in site.enclosure.gates:
                ax, ay = _gate_anchor_inside(site.enclosure, gate)
                _, _, length = gate
                # Each gate row should have a STREET tile on the
                # walkable side (at the anchor x, scanned over the
                # gate's y span).
                for dy in range(length):
                    assert _street_tile(site, ax, ay + dy), (
                        f"city seed={seed}: gate {gate} row "
                        f"y={ay+dy} not filled with STREET at "
                        f"anchor x={ax}; the spine widening picked "
                        f"the wrong perpendicular direction"
                    )

    def test_village_and_town_gates_fill_both_rows(self) -> None:
        for size_class in ("village", "town"):
            for seed in range(20):
                site = assemble_town(
                    f"{size_class}_seed{seed}", random.Random(seed),
                    size_class=size_class,
                )
                if site.enclosure is None:
                    continue  # hamlet has no palisade
                for gate in site.enclosure.gates:
                    ax, ay = _gate_anchor_inside(
                        site.enclosure, gate,
                    )
                    _, _, length = gate
                    for dy in range(length):
                        assert _street_tile(site, ax, ay + dy), (
                            f"{size_class} seed={seed}: gate "
                            f"{gate} row y={ay+dy} not filled "
                            f"with STREET at anchor x={ax}"
                        )

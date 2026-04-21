"""Town buildings get variable per-pair x-spacing.

Within a row, each adjacent pair picks its x-spacing from
``(0, 1, 3)`` with street-biased weights — most pairs still have
a proper street between them, some touch, some get a narrow
passage. Cross-building interior doors only fire for the
touching pairs (spacing == 0).
"""

from __future__ import annotations

import random

from nhc.dungeon.sites.town import assemble_town


def _row_pairs(site):
    """Return all (left, right) same-row adjacent building pairs."""
    rows: dict[int, list] = {}
    for b in site.buildings:
        rows.setdefault(b.base_rect.y, []).append(b)
    for row in rows.values():
        row.sort(key=lambda b: b.base_rect.x)
    pairs = []
    for row in rows.values():
        for left, right in zip(row, row[1:]):
            pairs.append((left, right))
    return pairs


class TestPerPairSpacingVaries:
    def test_at_least_two_distinct_gaps_across_seeds(self) -> None:
        """Across many seeds, adjacent pairs exhibit more than one
        distinct x-gap. Locks in the randomised pick (previously a
        fixed 3-tile gap)."""
        gaps: set[int] = set()
        for seed in range(30):
            site = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            for left, right in _row_pairs(site):
                gaps.add(right.base_rect.x - left.base_rect.x2)
            if len(gaps) >= 2:
                return
        assert len(gaps) >= 2, (
            f"expected varied spacing; got only {gaps}"
        )

    def test_spacings_are_from_allowed_set(self) -> None:
        """Every adjacent-pair gap is one of {0, 1, 3}."""
        allowed = {0, 1, 3}
        for seed in range(20):
            site = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            for left, right in _row_pairs(site):
                gap = right.base_rect.x - left.base_rect.x2
                assert gap in allowed, (
                    f"seed={seed}: adjacent pair "
                    f"{left.id}→{right.id} has gap {gap}, "
                    f"expected one of {allowed}"
                )


class TestInteriorDoorsRestrictedToTouchingPairs:
    def test_every_link_sits_on_touching_buildings(self) -> None:
        """Every InteriorDoorLink in a town connects two buildings
        whose base rects touch (left.x2 == right.x). Non-touching
        pairs never get doors even if their roles qualify."""
        found_any = False
        for seed in range(60):
            site = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            by_id = {b.id: b for b in site.buildings}
            for link in site.interior_door_links:
                found_any = True
                a = by_id[link.from_building]
                b = by_id[link.to_building]
                # Normalise left-right order.
                if a.base_rect.x > b.base_rect.x:
                    a, b = b, a
                assert a.base_rect.x2 == b.base_rect.x, (
                    f"seed={seed}: link {link} connects "
                    f"{a.id}(x={a.base_rect.x}-{a.base_rect.x2}) and "
                    f"{b.id}(x={b.base_rect.x}-{b.base_rect.x2}) — "
                    f"buildings are not touching"
                )
        assert found_any, (
            "expected at least one seed in 60 to produce a "
            "touching-pair door link"
        )

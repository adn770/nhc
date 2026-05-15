"""Tests for the ``scripts/site_inspect.py`` ad-hoc site inspector.

The inspector replaces the throwaway ``python -c`` snippets used to
verify macro-surface scatter counts. Its core (``inspect_site`` /
``aggregate``) is a pure function over a deterministic ``Random(seed)``,
so the same seeds always yield the same report.
"""

from __future__ import annotations

import pytest

from scripts.site_inspect import (
    SiteReport, aggregate, format_reports, inspect_site,
)

# Tower: base rect width = height in TOWER_SIZE_RANGE (7, 11) and the
# surface adds TOWER_SURFACE_PADDING (6) on every side, so the square
# surface dim is in [7 + 12, 11 + 12] = [19, 23].
TOWER_MIN_DIM = 7 + 2 * 6
TOWER_MAX_DIM = 11 + 2 * 6


class TestInspectSite:
    def test_returns_report_with_square_surface(self) -> None:
        r = inspect_site("tower", seed=0)
        assert isinstance(r, SiteReport)
        assert r.kind == "tower"
        assert r.seed == 0
        assert r.biome == "default"
        assert r.surface_w == r.surface_h
        assert TOWER_MIN_DIM <= r.surface_w <= TOWER_MAX_DIM

    def test_footprint_and_floors_sane(self) -> None:
        r = inspect_site("tower", seed=3)
        assert r.footprint_tiles > 0
        # TOWER_FLOOR_COUNT_RANGE is (2, 6).
        assert 2 <= r.floors <= 6

    def test_feature_counts_present_and_nonnegative(self) -> None:
        r = inspect_site("tower", seed=1)
        assert set(r.features) >= {"tree", "bush"}
        assert all(v >= 0 for v in r.features.values())

    def test_deterministic_for_same_seed(self) -> None:
        assert inspect_site("tower", seed=7) == inspect_site(
            "tower", seed=7,
        )

    def test_unknown_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown site kind"):
            inspect_site("dragon", seed=0)

    def test_unknown_biome_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown biome"):
            inspect_site("tower", seed=0, biome="atlantis")


class TestBiomeVegetationOrdering:
    """The resume's verified invariant: forest scatters more trees
    than the default, which scatters more than mountain."""

    def _tree_total(self, biome: str | None) -> int:
        return sum(
            r.features.get("tree", 0)
            for r in aggregate("tower", biome=biome, seeds=range(5))
        )

    def test_forest_gt_default_gt_mountain(self) -> None:
        forest = self._tree_total("forest")
        default = self._tree_total(None)
        mountain = self._tree_total("mountain")
        assert forest > default > mountain


class TestFormatReports:
    def test_summary_mentions_kind_and_counts(self) -> None:
        reports = aggregate("tower", seeds=range(2))
        out = format_reports(reports)
        assert "tower" in out
        assert "tree" in out
        assert "bush" in out
        # One data line per seed plus a header.
        assert out.count("\n") >= len(reports)

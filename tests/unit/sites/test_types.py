"""Tier enum + dim table contract.

After M6a the site system runs on five tiers (TINY / SMALL /
MEDIUM / LARGE / HUGE), spanning the cramped wayside-well footprint
all the way up to the macro city footprint. The dim table is the
canonical source of truth: every sub-hex assembler reads it
directly, and every macro assembler (post-M6b) reads it as the
default before applying any per-kind overrides.
"""

from __future__ import annotations

from nhc.sites._types import SITE_TIER_DIMS, SiteTier


def test_site_tier_has_five_values() -> None:
    """The five-step scale: TINY, SMALL, MEDIUM, LARGE, HUGE."""
    expected = {"TINY", "SMALL", "MEDIUM", "LARGE", "HUGE"}
    assert {t.name for t in SiteTier} == expected


def test_site_tier_dims_canonical_footprints() -> None:
    """Pin the canonical footprint per tier so the rebalance is
    explicit and any future drift surfaces in review."""
    assert SITE_TIER_DIMS[SiteTier.TINY] == (15, 10)
    assert SITE_TIER_DIMS[SiteTier.SMALL] == (30, 22)
    assert SITE_TIER_DIMS[SiteTier.MEDIUM] == (48, 44)
    assert SITE_TIER_DIMS[SiteTier.LARGE] == (72, 58)
    assert SITE_TIER_DIMS[SiteTier.HUGE] == (104, 86)


def test_site_tier_dims_strictly_grow() -> None:
    """Each tier is strictly larger (in both dimensions) than the
    previous one, so a tier override never accidentally shrinks a
    site footprint."""
    ordered = [
        SiteTier.TINY,
        SiteTier.SMALL,
        SiteTier.MEDIUM,
        SiteTier.LARGE,
        SiteTier.HUGE,
    ]
    for prev, curr in zip(ordered, ordered[1:]):
        pw, ph = SITE_TIER_DIMS[prev]
        cw, ch = SITE_TIER_DIMS[curr]
        assert cw > pw, f"{curr} width must exceed {prev}"
        assert ch > ph, f"{curr} height must exceed {prev}"

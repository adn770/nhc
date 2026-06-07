"""Town life M6: the street margins.

Beggars, drunks, buskers, urchins and a preacher add life at the
edges — peaceful errand NPCs that loiter and cluster around a few
gathering spots through the day and thin out at night. See
``design/town_life.md``.
"""

from __future__ import annotations

import random

import pytest

from nhc.entities.registry import EntityRegistry
from nhc.i18n import init as i18n_init
from nhc.i18n import t
from nhc.sites.town import (
    MARGIN_IDS,
    TOWN_MARGIN_COUNT,
    assemble_town,
)

MARGINS = ("beggar", "drunk", "busker", "urchin", "preacher")


# --- registry ----------------------------------------------------


@pytest.mark.parametrize("cid", MARGINS)
def test_margin_registers_as_peaceful_human(cid: str) -> None:
    EntityRegistry.discover_all()
    comps = EntityRegistry.get_creature(cid)
    assert comps["AI"].behavior == "errand"
    assert comps["AI"].faction == "human"
    assert "Errand" in comps


def test_margin_ids_match_roster() -> None:
    assert set(MARGIN_IDS) == set(MARGINS)


# --- locale ------------------------------------------------------


@pytest.mark.parametrize("lang", ["en", "ca", "es"])
@pytest.mark.parametrize("cid", MARGINS)
def test_locale_names_resolve(lang: str, cid: str) -> None:
    i18n_init(lang)
    for field in ("name", "short", "long"):
        val = t(f"creature.{cid}.{field}")
        assert val and not val.startswith("creature.")


@pytest.mark.parametrize("lang", ["ca", "es"])
@pytest.mark.parametrize("cid", MARGINS)
def test_gendered_locales_have_gender(lang: str, cid: str) -> None:
    i18n_init(lang)
    assert t(f"creature.{cid}.gender") in ("m", "f")


# --- population --------------------------------------------------


@pytest.mark.parametrize("size", ["hamlet", "village", "town", "city"])
def test_margin_count_within_range(size: str) -> None:
    lo, hi = TOWN_MARGIN_COUNT[size]
    for seed in range(12):
        site = assemble_town("t1", random.Random(seed), size_class=size)
        margins = [
            e for e in site.surface.entities
            if e.entity_id in MARGINS
        ]
        assert lo <= len(margins) <= hi


def test_margins_carry_loiter_routine() -> None:
    site = assemble_town("t1", random.Random(3), size_class="city")
    margins = [
        e for e in site.surface.entities if e.entity_id in MARGINS
    ]
    assert margins
    for m in margins:
        spec = m.extra.get("daily_routine")
        assert spec is not None
        assert "workplace" in spec and "home" in spec


def test_margins_cluster_on_few_gathering_spots() -> None:
    """Many margins share a small set of social anchors, so they
    visibly gather rather than scatter."""
    site = assemble_town("t1", random.Random(3), size_class="city")
    margins = [
        e for e in site.surface.entities if e.entity_id in MARGINS
    ]
    assert len(margins) >= 4
    spots = {tuple(m.extra["daily_routine"]["workplace"]) for m in margins}
    assert len(spots) <= 3

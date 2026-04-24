"""Cottage v2 populator (M11 of biome-features v2).

design/biome_features.md §8 calls for cottages to fill in the v1
populator TODO with a three-bucket roll:

* hermit (friendly, 40%)
* witch (hostile caster, 30%)
* abandoned (empty, 30%)

The NPC lands on the ground-floor room centre inside the cottage
building -- not on the outdoor surface -- so the door-crossing
handler delivers the encounter at the moment the player steps
inside. Cottage content is deterministic per seed so save / load
round-trips preserve it.
"""

from __future__ import annotations

import random

import pytest

from nhc.sites.cottage import (
    COTTAGE_CONTENT_WEIGHTS, assemble_cottage,
)
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.model import Biome
from nhc.i18n import init as i18n_init


@pytest.fixture(scope="module", autouse=True)
def _bootstrap() -> None:
    i18n_init("en")
    EntityRegistry.discover_all()


def _collect_interior_entities(site):
    """Return (entity_id, entity_type) tuples placed inside the
    cottage's ground floor."""
    building = site.buildings[0]
    return [
        (e.entity_id, e.entity_type)
        for e in building.ground.entities
    ]


# ── Three-bucket distribution ─────────────────────────────────────────


class TestCottageContentDistribution:
    def test_cottage_rolls_hermit_witch_or_abandoned(self):
        """Across 60 seeds all three outcomes must appear with
        frequency > 10% each so the three-bucket roll is really
        three-bucket (not a biased two-outcome split)."""
        counts = {"hermit": 0, "witch": 0, "abandoned": 0}
        for seed in range(60):
            site = assemble_cottage(
                f"c{seed}", random.Random(seed), biome=Biome.FOREST,
            )
            ids = [
                eid for eid, _ in _collect_interior_entities(site)
            ]
            if "hermit" in ids:
                counts["hermit"] += 1
            elif "witch" in ids:
                counts["witch"] += 1
            else:
                counts["abandoned"] += 1

        for label, n in counts.items():
            assert n >= 6, (
                f"{label} only rolled {n}/60 times; distribution "
                f"looks skewed ({counts})"
            )

    def test_cottage_content_weights_are_defined(self):
        """The module-level weights must sum to 1.0 and cover all
        three buckets."""
        total = sum(w for _, w in COTTAGE_CONTENT_WEIGHTS)
        assert abs(total - 1.0) < 0.01
        labels = {label for label, _ in COTTAGE_CONTENT_WEIGHTS}
        assert labels == {"hermit", "witch", "abandoned"}


# ── Per-outcome shape ─────────────────────────────────────────────────


def _first_roll_matching(label: str, max_seeds: int = 120):
    """Assemble cottages until one rolls to ``label``, and return it."""
    labels_seen = []
    for seed in range(max_seeds):
        site = assemble_cottage(
            f"probe{seed}", random.Random(seed), biome=Biome.FOREST,
        )
        ids = [e.entity_id for e in site.buildings[0].ground.entities]
        if label == "hermit" and "hermit" in ids:
            return site, seed
        if label == "witch" and "witch" in ids:
            return site, seed
        if label == "abandoned" and not ids:
            return site, seed
        labels_seen.append(ids)
    raise AssertionError(
        f"no seed in 0..{max_seeds} rolled {label!r}; "
        f"sampled: {labels_seen[:5]}"
    )


class TestCottageOutcomes:
    def test_hermit_cottage_has_friendly_hermit_npc(self):
        site, _ = _first_roll_matching("hermit")
        ents = _collect_interior_entities(site)
        hermits = [e for e in ents if e[0] == "hermit"]
        assert len(hermits) == 1

        comps = EntityRegistry.get_creature("hermit")
        ai = comps["AI"]
        # Friendly means not aggressive.
        assert "aggressive" not in ai.behavior
        # Neutral faction (no reprisal from player-aligned logic).
        assert ai.faction == "neutral"

    def test_witch_cottage_has_hostile_witch_creature(self):
        site, _ = _first_roll_matching("witch")
        ents = _collect_interior_entities(site)
        witches = [e for e in ents if e[0] == "witch"]
        assert len(witches) == 1

        comps = EntityRegistry.get_creature("witch")
        ai = comps["AI"]
        assert "aggressive" in ai.behavior

    def test_abandoned_cottage_has_no_entities(self):
        site, _ = _first_roll_matching("abandoned")
        assert site.surface.entities == []
        for b in site.buildings:
            for f in b.floors:
                assert f.entities == []

    def test_cottage_content_is_deterministic_for_same_seed(self):
        site_a = assemble_cottage(
            "det", random.Random(77), biome=Biome.FOREST,
        )
        site_b = assemble_cottage(
            "det", random.Random(77), biome=Biome.FOREST,
        )
        ids_a = [
            e.entity_id for e in site_a.buildings[0].ground.entities
        ]
        ids_b = [
            e.entity_id for e in site_b.buildings[0].ground.entities
        ]
        assert ids_a == ids_b


# ── Placement -- indoors, not on the surface ──────────────────────────


class TestCottageNPCPlacement:
    def test_hermit_is_placed_inside_the_building(self):
        site, _ = _first_roll_matching("hermit")
        # Interior has the hermit.
        interior_ids = {
            e.entity_id for e in site.buildings[0].ground.entities
        }
        assert "hermit" in interior_ids
        # Surface does not.
        surface_ids = {
            e.entity_id for e in site.surface.entities
        }
        assert "hermit" not in surface_ids

    def test_witch_is_placed_inside_the_building(self):
        site, _ = _first_roll_matching("witch")
        interior_ids = {
            e.entity_id for e in site.buildings[0].ground.entities
        }
        assert "witch" in interior_ids
        surface_ids = {
            e.entity_id for e in site.surface.entities
        }
        assert "witch" not in surface_ids


# ── Locale sanity ─────────────────────────────────────────────────────


class TestCottageNPCLocales:
    @pytest.mark.parametrize("entity_id", ["hermit", "witch"])
    @pytest.mark.parametrize("lang", ["en", "ca", "es"])
    def test_npc_has_locale_entries(self, entity_id, lang):
        from nhc.i18n.manager import TranslationManager
        mgr = TranslationManager()
        mgr.load(lang)
        assert (mgr.get(f"creature.{entity_id}.name")
                != f"creature.{entity_id}.name")
        assert (mgr.get(f"creature.{entity_id}.short")
                != f"creature.{entity_id}.short")

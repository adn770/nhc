"""ARCHETYPE_CONFIG wiring guards (M14).

Every archetype string referenced by a site assembler must
resolve in :data:`ARCHETYPE_CONFIG`. These tests act as a typo
guard — adding a new archetype site requires adding the config
entry, and removing a config entry surfaces the mismatch here
before it reaches runtime.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.interior._floor import resolve_partitioner
from nhc.dungeon.interior.registry import ARCHETYPE_CONFIG
from nhc.dungeon.sites.cottage import assemble_cottage
from nhc.dungeon.sites.farm import assemble_farm
from nhc.dungeon.sites.keep import assemble_keep
from nhc.dungeon.sites.mansion import assemble_mansion
from nhc.dungeon.sites.ruin import assemble_ruin
from nhc.dungeon.sites.temple import assemble_temple
from nhc.dungeon.sites.tower import assemble_tower


SITE_ASSEMBLERS: list[tuple[str, object]] = [
    ("tower", assemble_tower),
    ("cottage", assemble_cottage),
    ("farm", assemble_farm),
    ("keep", assemble_keep),
    ("mansion", assemble_mansion),
    ("ruin", assemble_ruin),
    ("temple", assemble_temple),
]


class TestRegistryCompleteness:
    @pytest.mark.parametrize("name,spec", list(ARCHETYPE_CONFIG.items()))
    def test_every_archetype_resolves_to_a_partitioner(self, name, spec):
        resolve_partitioner(spec)

    def test_unknown_archetype_raises_keyerror(self):
        with pytest.raises(KeyError):
            ARCHETYPE_CONFIG["nonexistent_archetype"]


class TestSiteArchetypeMaterials:
    @pytest.mark.parametrize("name,assemble", SITE_ASSEMBLERS)
    def test_every_site_sets_interior_wall_material(
        self, name, assemble,
    ):
        """Every site reads its ``interior_wall_material`` from the
        registry — it must land on a known material, not the
        dataclass default silently leaking through."""
        site = assemble(f"{name}1", random.Random(1))
        for building in site.buildings:
            assert building.interior_wall_material in (
                "wood", "stone", "brick",
            ), f"{name}: unexpected material " \
               f"{building.interior_wall_material!r}"

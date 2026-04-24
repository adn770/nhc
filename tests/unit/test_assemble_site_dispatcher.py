"""Tests for the assemble_site() dispatcher.

See design/building_generator.md section 10. A single entry point
routes a ``kind`` string to the right concrete assembler.
"""

from __future__ import annotations

import random

import pytest

from nhc.sites._site import Site, assemble_site


class TestAssembleSiteDispatcher:
    @pytest.mark.parametrize(
        "kind",
        ["tower", "farm", "mansion", "keep", "town"],
    )
    def test_returns_site_with_matching_kind(self, kind: str):
        site = assemble_site(kind, "s1", random.Random(1))
        assert isinstance(site, Site)
        assert site.kind == kind

    def test_unknown_kind_raises_value_error(self):
        with pytest.raises(ValueError, match="unknown site kind"):
            assemble_site("keepzilla", "s1", random.Random(1))

    def test_empty_kind_raises(self):
        with pytest.raises(ValueError):
            assemble_site("", "s1", random.Random(1))


class TestAssembleSiteDeterminism:
    @pytest.mark.parametrize(
        "kind",
        ["tower", "farm", "mansion", "keep", "town"],
    )
    def test_dispatcher_preserves_determinism(self, kind: str):
        s1 = assemble_site(kind, "s1", random.Random(42))
        s2 = assemble_site(kind, "s1", random.Random(42))
        assert len(s1.buildings) == len(s2.buildings)
        assert (s1.enclosure is None) == (s2.enclosure is None)

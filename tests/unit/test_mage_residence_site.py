"""Mage residence assembler tests (M19).

See ``design/building_interiors.md``. The mage residence draws
from the ``mage_residence`` archetype (enriched SectorPartitioner)
on an octagon or circle footprint. Regular towers stay on
circle / octagon / square with the simple sector / divided
partitioners.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import CircleShape, OctagonShape, Terrain
from nhc.sites._site import Site
from nhc.sites.mage_residence import (
    MAGE_GARDEN_TREE_SPACING,
    MAGE_SURFACE_PADDING,
    assemble_mage_residence,
)
from nhc.sites.tower import assemble_tower


def _features(surface):
    feats: dict[tuple[int, int], str] = {}
    for y, row in enumerate(surface.tiles):
        for x, tile in enumerate(row):
            if tile.feature is not None:
                feats[(x, y)] = tile.feature
    return feats


class TestMageResidenceBasics:
    def test_returns_site_with_one_building(self):
        site = assemble_mage_residence(
            "m1", random.Random(1),
        )
        assert isinstance(site, Site)
        assert site.kind == "mage_residence"
        assert len(site.buildings) == 1

    def test_shape_is_octagon_or_circle(self):
        for seed in range(30):
            site = assemble_mage_residence(
                "m1", random.Random(seed),
            )
            shape = site.buildings[0].base_shape
            assert isinstance(shape, (CircleShape, OctagonShape))

    def test_interior_wall_material_is_stone(self):
        site = assemble_mage_residence("m1", random.Random(1))
        assert site.buildings[0].interior_wall_material == "stone"

    def test_main_sector_rotates_across_floors(self):
        """Enriched SectorPartitioner tags exactly one room per
        floor as ``"main"``; the index rotates with floor."""
        for seed in range(30):
            site = assemble_mage_residence(
                "m1", random.Random(seed),
            )
            b = site.buildings[0]
            if len(b.floors) < 2:
                continue
            mains: list[int] = []
            for floor in b.floors:
                for i, room in enumerate(floor.rooms):
                    if "main" in room.tags:
                        mains.append(i)
                        break
            if len(mains) >= 2 and len(set(mains)) >= 2:
                return
        # Every seed we tried produced a single floor or identical
        # mains — unlikely; the assertion fails loud if it happens.
        raise AssertionError(
            "no mage-residence seed produced a rotating main sector"
        )


class TestMageGarden:
    """The residence sits in a bigger, well-kept garden: a bush
    hedge borders the grounds and trees are planted on a regular
    geometric lattice (not a random scatter)."""

    def test_surface_is_padded_around_the_footprint(self):
        for seed in range(8):
            site = assemble_mage_residence("m1", random.Random(seed))
            b = site.buildings[0]
            r = b.base_rect
            s = site.surface
            # Symmetric padding on every side of the base rect.
            assert r.x >= MAGE_SURFACE_PADDING
            assert r.y >= MAGE_SURFACE_PADDING
            assert s.width >= r.x + r.width + MAGE_SURFACE_PADDING
            assert s.height >= r.y + r.height + MAGE_SURFACE_PADDING

    def test_has_both_trees_and_bushes(self):
        site = assemble_mage_residence("m1", random.Random(3))
        kinds = set(_features(site.surface).values())
        assert "tree" in kinds
        assert "bush" in kinds

    def test_bush_hedge_borders_the_playable_area(self):
        site = assemble_mage_residence("m1", random.Random(3))
        s = site.surface
        feats = _features(s)
        # The four playable-border corners (just inside the 1-tile
        # VOID margin) are hedge bushes — a deterministic border.
        for corner in [
            (1, 1), (s.width - 2, 1),
            (1, s.height - 2), (s.width - 2, s.height - 2),
        ]:
            assert feats.get(corner) == "bush", corner

    def test_trees_sit_on_a_geometric_lattice(self):
        # Every tree must land on the centred lattice — proves the
        # placement is sorted/geometric, not a random scatter.
        for seed in range(8):
            site = assemble_mage_residence("m1", random.Random(seed))
            s = site.surface
            cx, cy = s.width // 2, s.height // 2
            sp = MAGE_GARDEN_TREE_SPACING
            trees = [
                xy for xy, f in _features(s).items() if f == "tree"
            ]
            assert trees, f"seed {seed}: no trees planted"
            for (x, y) in trees:
                assert (x - cx) % sp == 0 and (y - cy) % sp == 0, (
                    f"seed {seed}: tree {(x, y)} off lattice"
                )

    def test_void_margin_preserved(self):
        site = assemble_mage_residence("m1", random.Random(5))
        s = site.surface
        for x in range(s.width):
            assert s.tiles[0][x].terrain is Terrain.VOID
            assert s.tiles[s.height - 1][x].terrain is Terrain.VOID
        for y in range(s.height):
            assert s.tiles[y][0].terrain is Terrain.VOID
            assert s.tiles[y][s.width - 1].terrain is Terrain.VOID


class TestTowerStaysSimple:
    def test_tower_never_tags_main_sector(self):
        """Regular towers use simple (not enriched) sector mode —
        no ``"main"`` tag lands on any room."""
        for seed in range(20):
            site = assemble_tower("t1", random.Random(seed))
            for floor in site.buildings[0].floors:
                for room in floor.rooms:
                    assert "main" not in room.tags

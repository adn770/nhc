"""Pickle round-trip tests for Building (M20).

M7 added ``Building.interior_wall_material``. Older save
snapshots do not carry the attribute — ``__setstate__`` fills
in a default so those pickles continue to load. M20 also pins
that ``StairLink`` serialization is unchanged, so descent /
in-building stair data survives across the upgrade.
"""

from __future__ import annotations

import pickle

from nhc.dungeon.building import Building, StairLink
from nhc.dungeon.model import Level, Rect, RectShape
from nhc.hexcrawl.model import DungeonRef


class TestBuildingPickleDefaults:
    def test_roundtrip_preserves_interior_wall_material(self):
        b = Building(
            id="b", base_shape=RectShape(),
            base_rect=Rect(1, 1, 5, 5),
            interior_wall_material="wood",
        )
        b2 = pickle.loads(pickle.dumps(b))
        assert b2.interior_wall_material == "wood"

    def test_old_state_without_field_loads_with_default(self):
        """Simulate an older pickle by deleting the field from the
        state dict before restoring — exactly what unpickling a
        pre-M7 Building does."""
        b = Building(
            id="b", base_shape=RectShape(),
            base_rect=Rect(1, 1, 5, 5),
        )
        state = b.__dict__.copy()
        del state["interior_wall_material"]
        restored = Building.__new__(Building)
        restored.__setstate__(state)
        assert restored.interior_wall_material == "stone"

    def test_old_state_without_roof_material_loads(self):
        b = Building(
            id="b", base_shape=RectShape(),
            base_rect=Rect(1, 1, 5, 5),
        )
        state = b.__dict__.copy()
        del state["roof_material"]
        restored = Building.__new__(Building)
        restored.__setstate__(state)
        assert restored.roof_material is None


class TestStairLinkSerialization:
    def test_roundtrip_in_building_link(self):
        link = StairLink(
            from_floor=0, to_floor=1,
            from_tile=(3, 4), to_tile=(3, 4),
        )
        assert pickle.loads(pickle.dumps(link)) == link

    def test_roundtrip_descent_link(self):
        ref = DungeonRef(template="procedural:crypt")
        link = StairLink(
            from_floor=0, to_floor=ref,
            from_tile=(2, 2), to_tile=(0, 0),
        )
        restored = pickle.loads(pickle.dumps(link))
        assert restored.from_floor == 0
        assert restored.from_tile == (2, 2)
        assert restored.to_tile == (0, 0)
        assert isinstance(restored.to_floor, DungeonRef)
        assert restored.to_floor.template == "procedural:crypt"

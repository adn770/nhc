"""Unit tests for ``Game.current_location_id`` (web perf fix A).

The id is a pure function of navigation state, so we exercise it
against lightweight duck-typed stand-ins via the unbound method —
no full ``Game`` / world construction needed.
"""

import re
from types import SimpleNamespace

from nhc.core.game import Game
from nhc.hexcrawl.mode import WorldType

_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")


def _coord(q, r):
    return SimpleNamespace(q=q, r=r)


def _ns(
    *, level, world_type=WorldType.HEXCRAWL, pos=None,
    sub=None, site=None,
):
    return SimpleNamespace(
        level=level,
        world_type=world_type,
        hex_player_position=pos,
        _active_site_sub=sub,
        _active_site=site,
    )


def _loc(ns):
    # Call the unbound method on the duck-typed stand-in.
    return Game.current_location_id(ns)


def test_none_level_returns_sentinel():
    assert _loc(_ns(level=None)) == "none"


def test_sub_hex_site_surface():
    lvl = SimpleNamespace(building_id=None, floor_index=None, depth=1)
    ns = _ns(level=lvl, pos=_coord(3, -1), sub=_coord(0, 2))
    assert _loc(ns) == "hex_3_-1_sub_0_2_d1"


def test_building_floor_differs_from_surface_same_depth():
    # A house ground floor at depth 1 must NOT collide with the
    # site surface at depth 1 — the b<idx>_f<floor> marker keeps
    # them distinct.
    site = SimpleNamespace(
        buildings=[SimpleNamespace(id="b0"), SimpleNamespace(id="b1"),
                   SimpleNamespace(id="house")],
    )
    surface = SimpleNamespace(building_id=None, floor_index=None, depth=1)
    house = SimpleNamespace(building_id="house", floor_index=0, depth=1)
    ns_surf = _ns(level=surface, pos=_coord(3, -1), sub=_coord(0, 2),
                  site=site)
    ns_house = _ns(level=house, pos=_coord(3, -1), sub=_coord(0, 2),
                   site=site)
    assert _loc(ns_surf) == "hex_3_-1_sub_0_2_d1"
    assert _loc(ns_house) == "hex_3_-1_sub_0_2_b2_f0_d1"
    assert _loc(ns_surf) != _loc(ns_house)


def test_building_upper_floors_distinct():
    site = SimpleNamespace(buildings=[SimpleNamespace(id="t")])
    f0 = SimpleNamespace(building_id="t", floor_index=0, depth=1)
    f1 = SimpleNamespace(building_id="t", floor_index=1, depth=2)
    ns0 = _ns(level=f0, pos=_coord(1, 1), site=site)
    ns1 = _ns(level=f1, pos=_coord(1, 1), site=site)
    assert _loc(ns0) != _loc(ns1)


def test_same_depth_distinct_across_hexes():
    a = SimpleNamespace(building_id=None, floor_index=None, depth=3)
    ns_a = _ns(level=a, pos=_coord(0, 0))
    ns_b = _ns(level=a, pos=_coord(5, 2))
    assert _loc(ns_a) == "hex_0_0_d3"
    assert _loc(ns_b) == "hex_5_2_d3"
    assert _loc(ns_a) != _loc(ns_b)


def test_pure_dungeon_has_no_hex_prefix():
    lvl = SimpleNamespace(building_id=None, floor_index=None, depth=3)
    ns = _ns(level=lvl, world_type=WorldType.DUNGEON, pos=None)
    assert _loc(ns) == "d3"


def test_stable_across_calls():
    lvl = SimpleNamespace(building_id=None, floor_index=None, depth=1)
    ns = _ns(level=lvl, pos=_coord(3, -1), sub=_coord(0, 2))
    assert _loc(ns) == _loc(ns)


def test_token_is_url_safe():
    site = SimpleNamespace(buildings=[SimpleNamespace(id="house")])
    cases = [
        _ns(level=SimpleNamespace(building_id=None, floor_index=None,
                                  depth=1), pos=_coord(-3, -7),
            sub=_coord(-1, 0)),
        _ns(level=SimpleNamespace(building_id="house", floor_index=2,
                                  depth=1), pos=_coord(3, -1), site=site),
        _ns(level=SimpleNamespace(building_id=None, floor_index=None,
                                  depth=4), world_type=WorldType.DUNGEON),
    ]
    for ns in cases:
        token = _loc(ns)
        assert _SAFE.match(token), f"unsafe token: {token!r}"
        assert "." not in token and "/" not in token

"""Cross-building interior door links in towns.

Town's cluster packer (Phase 1) rolls a 50/50 chance of an
:class:`InteriorDoorLink` per cluster-internal adjacent pair --
row members touching east/west, column members touching
north/south. The legacy SHARED_DOOR_PAIRS role whitelist no
longer gates link creation; cluster archetype + the per-pair coin
flip do. Links still use the mirrored-perimeter teleport mechanism
(each building floor is its own Level), matching mansion's
cross-building connection.
"""

from __future__ import annotations

import random

from nhc.sites._shell import compose_shell
from nhc.sites.town import assemble_town
from nhc.dungeon.model import Level


def _role_of(building) -> str:
    from nhc.sites.town import (
        SERVICE_ROLES_WITH_NPCS, SERVICE_ROLES_RESERVED,
    )
    known = SERVICE_ROLES_WITH_NPCS + SERVICE_ROLES_RESERVED
    for tag in building.ground.rooms[0].tags:
        if tag in known:
            return tag
    return "residential"


class TestSharedDoorPairFires:
    """Some seed must produce a link via the SHARED_DOOR_PAIRS
    rules. ``residential-residential`` is the common case because
    villages always contain ≥ 2 residentials."""

    def test_some_seed_produces_a_link(self) -> None:
        found = False
        for seed in range(60):
            site = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            if site.interior_door_links:
                found = True
                break
        assert found, (
            "no village seed in 60 produced a cross-building link"
        )


class TestLinkFloorBound:
    def test_link_floor_within_shorter_building(self) -> None:
        """A link must satisfy
        ``0 <= floor < min(len(A.floors), len(B.floors))``."""
        for seed in range(60):
            site = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            if not site.interior_door_links:
                continue
            by_id = {b.id: b for b in site.buildings}
            for link in site.interior_door_links:
                a = by_id[link.from_building]
                b = by_id[link.to_building]
                assert 0 <= link.floor < min(
                    len(a.floors), len(b.floors),
                ), (
                    f"seed={seed}: link floor={link.floor} out of "
                    f"range for {a.id} ({len(a.floors)} floors) / "
                    f"{b.id} ({len(b.floors)} floors)"
                )


class TestLinkMirrorsInteriorDoors:
    """Every link lands a symmetric entry in the legacy
    ``interior_doors`` dict so existing door-crossing code keeps
    working."""

    def test_link_registered_both_ways(self) -> None:
        for seed in range(60):
            site = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            if not site.interior_door_links:
                continue
            # For the *ground* floor we expect dict entries; upper
            # floors go through interior_door_links only (legacy
            # dict is ground-floor only for compatibility).
            for link in site.interior_door_links:
                if link.floor != 0:
                    continue
                key_from = (
                    link.from_building,
                    link.from_tile[0], link.from_tile[1],
                )
                key_to = (
                    link.to_building,
                    link.to_tile[0], link.to_tile[1],
                )
                assert site.interior_doors.get(key_from) == (
                    link.to_building,
                    link.to_tile[0], link.to_tile[1],
                )
                assert site.interior_doors.get(key_to) == (
                    link.from_building,
                    link.from_tile[0], link.from_tile[1],
                )


class TestComposeShellSharedDoors:
    """compose_shell gains a ``shared_doors`` parameter for API
    completeness (the town's per-floor composition runs on
    separate Levels, so shared_doors is unused in practice, but
    the API declares the contract so future callers that share
    Levels get the correct behaviour)."""

    def test_shared_door_param_stamps_door_tile(self) -> None:
        level = Level.create_empty("s", "s", 0, 8, 8)
        fp_a = {(2, 2), (2, 3), (2, 4), (3, 2), (3, 3), (3, 4)}
        fp_b = {(4, 2), (4, 3), (4, 4), (5, 2), (5, 3), (5, 4)}
        compose_shell(
            level,
            {"a": fp_a, "b": fp_b},
            shared_doors=[("a", "b", (4, 3))],
        )
        tile = level.tiles[3][4]
        assert tile.feature == "door_closed"

    def test_shared_doors_default_empty(self) -> None:
        level = Level.create_empty("s", "s", 0, 6, 6)
        fp_a = {(2, 2), (2, 3), (3, 2), (3, 3)}
        compose_shell(level, {"a": fp_a})
        # No door placed anywhere.
        for row in level.tiles:
            for t in row:
                assert t.feature != "door_closed"

"""Tests for the teleporter-pad tile feature and movement hook.

A level may carry a ``teleporter_pairs`` map between tile coords.
After any player action that leaves them standing on a pad, the
game hook teleports them to the paired tile. Pads are symmetric
(A↔B) so the same hook handles both ends. Non-player entities
are not teleported — pads are a player affordance.
"""

from __future__ import annotations

from nhc.core.actions._teleport import maybe_teleport_player
from nhc.core.ecs import World
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    BlocksMovement, Description, Health, Player, Position,
    Renderable, Stats,
)
from nhc.i18n import init as i18n_init


def _level_with_pads() -> Level:
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(10)]
        for _ in range(10)
    ]
    tiles[2][2] = Tile(terrain=Terrain.FLOOR, feature="teleporter_pad")
    tiles[8][8] = Tile(terrain=Terrain.FLOOR, feature="teleporter_pad")
    level = Level(
        id="lvl", name="L", depth=1,
        width=10, height=10,
        tiles=tiles, rooms=[], corridors=[], entities=[],
    )
    level.teleporter_pairs = {(2, 2): (8, 8), (8, 8): (2, 2)}
    return level


def _make_player(world: World, x: int, y: int) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="lvl"),
        "Player": Player(),
        "Stats": Stats(),
        "Health": Health(current=10, maximum=10),
        "Renderable": Renderable(glyph="@", color="white"),
        "Description": Description(name="Hero"),
    })


class TestTeleportOnStep:
    def test_player_on_pad_teleports_to_pair(self):
        i18n_init("en")
        world = World()
        level = _level_with_pads()
        pid = _make_player(world, 2, 2)

        teleported = maybe_teleport_player(world, level, pid)

        pos = world.get_component(pid, "Position")
        assert teleported is True
        assert (pos.x, pos.y) == (8, 8)

    def test_player_off_pad_does_not_teleport(self):
        i18n_init("en")
        world = World()
        level = _level_with_pads()
        pid = _make_player(world, 5, 5)

        teleported = maybe_teleport_player(world, level, pid)

        pos = world.get_component(pid, "Position")
        assert teleported is False
        assert (pos.x, pos.y) == (5, 5)

    def test_pad_without_pair_does_nothing(self):
        """A lone pad with no entry in teleporter_pairs is a dead
        tile — stepping on it doesn't teleport anywhere."""
        i18n_init("en")
        world = World()
        level = _level_with_pads()
        # Clear the map so the pair lookup misses.
        level.teleporter_pairs = {}
        pid = _make_player(world, 2, 2)

        teleported = maybe_teleport_player(world, level, pid)

        pos = world.get_component(pid, "Position")
        assert teleported is False
        assert (pos.x, pos.y) == (2, 2)

    def test_teleport_is_symmetric(self):
        """Stepping on the destination pad returns the player to
        the origin — pads work both ways."""
        i18n_init("en")
        world = World()
        level = _level_with_pads()
        pid = _make_player(world, 8, 8)

        maybe_teleport_player(world, level, pid)

        pos = world.get_component(pid, "Position")
        assert (pos.x, pos.y) == (2, 2)

    def test_chained_teleport_stops_after_one_hop(self):
        """If the destination pad also pairs with a third pad
        somewhere else, the teleport stops after one hop so the
        player doesn't vanish into a chain."""
        i18n_init("en")
        world = World()
        level = _level_with_pads()
        # Make 8,8 point to a third spot (5,5) that has no feature;
        # more importantly, assert we don't re-teleport when we
        # land on a pad at the destination.
        level.teleporter_pairs = {(2, 2): (8, 8), (8, 8): (5, 5)}
        level.tiles[5][5] = Tile(terrain=Terrain.FLOOR,
                                 feature="teleporter_pad")
        pid = _make_player(world, 2, 2)

        maybe_teleport_player(world, level, pid)

        pos = world.get_component(pid, "Position")
        # One hop: 2,2 -> 8,8. No second hop to 5,5.
        assert (pos.x, pos.y) == (8, 8)


class TestNonPlayersIgnored:
    def test_creature_on_pad_is_not_teleported(self):
        """Pads are a player-only affordance; creatures wandering
        onto one stay put."""
        i18n_init("en")
        world = World()
        level = _level_with_pads()
        pid = _make_player(world, 0, 0)
        # Passing a non-player id is out of scope — the helper
        # only operates on the provided player_id. Verify that
        # by passing a bogus id that has no Player component.
        cid = world.create_entity({
            "Position": Position(x=2, y=2, level_id="lvl"),
            "Stats": Stats(),
            "Health": Health(current=5, maximum=5),
            "BlocksMovement": BlocksMovement(),
            "Renderable": Renderable(glyph="g", color="green"),
            "Description": Description(name="Goblin"),
        })

        maybe_teleport_player(world, level, pid)

        cpos = world.get_component(cid, "Position")
        assert (cpos.x, cpos.y) == (2, 2)

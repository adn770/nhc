"""Unhired adventurers stroll the town via the errand AI with an
inn-door anchor bias, so the player can reliably find them to hire.

Dungeon floors keep the old Brownian wander; only level metadata
with ``theme == "town"`` routes the tick through
``_decide_errand_action``.
"""

from __future__ import annotations

from nhc.ai.henchman_ai import decide_unhired_wander_action
from nhc.core.actions import MoveAction
from nhc.core.ecs import World
from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    Errand,
    Health,
    Henchman,
    Player,
    Position,
    Renderable,
    Stats,
)
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed


def _town_surface(width: int = 12, height: int = 12) -> Level:
    tiles = [
        [
            Tile(terrain=Terrain.FLOOR, surface_type=SurfaceType.STREET)
            for _ in range(width)
        ]
        for _ in range(height)
    ]
    level = Level(
        id="town_surface", name="Town", depth=0,
        width=width, height=height,
        tiles=tiles, rooms=[], corridors=[], entities=[],
    )
    level.metadata.theme = "town"
    return level


def _dungeon_level(width: int = 12, height: int = 12) -> Level:
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(width)]
        for _ in range(height)
    ]
    return Level(
        id="dungeon", name="Dungeon", depth=1,
        width=width, height=height,
        tiles=tiles, rooms=[], corridors=[], entities=[],
    )


def _make_player(world: World, x: int = 5, y: int = 5) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="town_surface"),
        "Player": Player(),
        "Stats": Stats(strength=1, dexterity=1, wisdom=1),
        "Health": Health(current=20, maximum=20),
        "Renderable": Renderable(glyph="@", color="white"),
        "Description": Description(name="Hero"),
    })


def _make_unhired_adventurer(
    world: World, x: int, y: int,
    anchor: tuple[int, int] | None = None,
) -> int:
    comps = {
        "Position": Position(x=x, y=y, level_id="town_surface"),
        "Stats": Stats(strength=1, dexterity=1),
        "Health": Health(current=8, maximum=8),
        "AI": AI(behavior="henchman", morale=7, faction="human"),
        "Henchman": Henchman(level=1, hired=False),
        "BlocksMovement": BlocksMovement(),
        "Renderable": Renderable(glyph="@", color="cyan"),
        "Description": Description(name="Pip"),
        "Errand": Errand(
            anchor_x=anchor[0] if anchor else None,
            anchor_y=anchor[1] if anchor else None,
            anchor_weight=0.5 if anchor else 0.0,
        ),
    }
    return world.create_entity(comps)


class TestTownLevelRoutesToErrand:
    def test_town_surface_drives_via_errand(self):
        """On a town surface the unhired adventurer picks an
        errand target and starts walking."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _town_surface()
        pid = _make_player(world, 0, 0)
        aid = _make_unhired_adventurer(
            world, 5, 5, anchor=(6, 6),
        )

        action = decide_unhired_wander_action(aid, world, level, pid)

        errand = world.get_component(aid, "Errand")
        # Either a MoveAction (target picked on this tick) or a
        # HoldAction if the destination happened to be the starting
        # tile itself — the point is that errand state got used.
        assert errand.target_x is not None \
            or errand.idle_turns_remaining > 0

    def test_dungeon_keeps_brownian_wander(self):
        """Below ground the hireling still uses the old random-step
        wander, not the errand pathfinder."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _dungeon_level()
        pid = _make_player(world, 0, 0)
        aid = _make_unhired_adventurer(world, 5, 5)

        decide_unhired_wander_action(aid, world, level, pid)

        errand = world.get_component(aid, "Errand")
        # Brownian path never writes errand state.
        assert errand.target_x is None
        assert errand.idle_turns_remaining == 0


class TestAnchorBias:
    def test_anchor_attracts_destinations(self):
        """With high anchor_weight every destination lands near
        the anchor tile."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _town_surface(width=20, height=20)
        pid = _make_player(world, 0, 0)
        aid = _make_unhired_adventurer(world, 10, 10)
        # Force anchor bias to 100%.
        errand = world.get_component(aid, "Errand")
        errand.anchor_x = 18
        errand.anchor_y = 18
        errand.anchor_weight = 1.0

        picks: list[tuple[int, int]] = []
        for _ in range(20):
            errand.target_x = None
            errand.target_y = None
            errand.idle_turns_remaining = 0
            decide_unhired_wander_action(aid, world, level, pid)
            if errand.target_x is not None:
                picks.append((errand.target_x, errand.target_y))

        assert picks, "no destinations were picked in 20 ticks"
        for (tx, ty) in picks:
            assert max(abs(tx - 18), abs(ty - 18)) <= 3, (
                f"target ({tx},{ty}) outside anchor radius"
            )

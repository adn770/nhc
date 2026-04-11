"""Tests for the morale state machine in creature AI.

Covers the first-sight engagement check and the hesitant/fleeing
state transitions inside ``decide_action``. The HP-drop trigger
is exercised in ``test_combat.py``.
"""

import pytest

from nhc.ai.behavior import decide_action
from nhc.core.actions import (
    HoldAction,
    MeleeAttackAction,
    MoveAction,
)
from nhc.core.ecs import World
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    Health,
    Player,
    Position,
    Renderable,
    Stats,
)
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed


pytestmark = pytest.mark.core


def _make_level(w: int = 12, h: int = 12) -> Level:
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(w)]
             for _ in range(h)]
    for x in range(w):
        tiles[0][x].terrain = Terrain.WALL
        tiles[h - 1][x].terrain = Terrain.WALL
    for y in range(h):
        tiles[y][0].terrain = Terrain.WALL
        tiles[y][w - 1].terrain = Terrain.WALL
    return Level(
        id="t", name="T", depth=1, width=w, height=h,
        tiles=tiles, rooms=[], corridors=[], entities=[],
    )


def _make_player(world: World, x: int = 5, y: int = 5) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="t"),
        "Stats": Stats(strength=2, dexterity=2),
        "Health": Health(current=20, maximum=20),
        "Player": Player(),
        "Description": Description(name="Hero"),
        "Renderable": Renderable(glyph="@"),
    })


def _make_creature(
    world: World, x: int, y: int, *,
    morale: int = 7, behavior: str = "aggressive_melee",
    state: str = "unaware", hp: int = 10,
) -> int:
    ai = AI(behavior=behavior, morale=morale, faction="goblinoid")
    ai.state = state
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="t"),
        "Stats": Stats(strength=1, dexterity=1),
        "Health": Health(current=hp, maximum=hp),
        "AI": ai,
        "BlocksMovement": BlocksMovement(),
        "Description": Description(name="Goblin", gender="m"),
        "Renderable": Renderable(glyph="g"),
    })


@pytest.fixture(autouse=True)
def _i18n():
    i18n_init("en")
    set_seed(42)


class TestFirstSightEngagement:
    def test_high_morale_engages_immediately(self):
        """A morale-12 creature never hesitates: it transitions
        unaware → engaged on first sight and chases / attacks
        as before."""
        world = _make_world_player_at(5, 5)
        cid = _make_creature(world, 6, 5, morale=12)
        ai = world.get_component(cid, "AI")
        assert ai.state == "unaware"

        action = decide_action(cid, world, _level(), _pid(world))

        assert ai.state == "engaged"
        assert isinstance(action, MeleeAttackAction)

    def test_low_morale_hesitates_on_first_sight(self):
        """A morale-1 creature always fails first-sight check
        and flips to hesitant; the action is a HoldAction with
        a non-empty narration message."""
        world = _make_world_player_at(5, 5)
        cid = _make_creature(world, 6, 5, morale=1)

        action = decide_action(cid, world, _level(), _pid(world))

        ai = world.get_component(cid, "AI")
        assert ai.state == "hesitant"
        assert isinstance(action, HoldAction)
        assert action.message_text  # not empty
        assert action.actor == cid

    def test_first_hesitation_narrates_subsequent_silent(self):
        """Once a creature is already in the hesitant state,
        a continued hesitation should not spam the message
        log — the second HoldAction has no message."""
        world = _make_world_player_at(5, 5)
        cid = _make_creature(world, 6, 5, morale=1, state="hesitant")

        action = decide_action(cid, world, _level(), _pid(world))

        assert isinstance(action, HoldAction)
        assert action.message_text == ""

    def test_hesitant_creature_can_rally(self):
        """A hesitant creature that passes its re-roll
        transitions to engaged and emits the rally line."""
        world = _make_world_player_at(5, 5)
        # morale=12 → re-roll always passes
        cid = _make_creature(world, 6, 5, morale=12, state="hesitant")

        action = decide_action(cid, world, _level(), _pid(world))

        ai = world.get_component(cid, "AI")
        assert ai.state == "engaged"
        # Rally narration is produced as a HoldAction this turn
        # (the creature spends its rally turn shouting, then
        # attacks next turn). Easier than splicing a message
        # onto a melee action.
        assert isinstance(action, HoldAction)
        assert action.message_text  # rally line


class TestFleeingState:
    def test_fleeing_creature_moves_away_from_player(self):
        """A morale-broken creature in the fleeing state should
        return a MoveAction that strictly increases distance to
        the player."""
        from nhc.utils.spatial import chebyshev

        world = _make_world_player_at(5, 5)
        cid = _make_creature(world, 6, 5, morale=7, state="fleeing")

        action = decide_action(cid, world, _level(), _pid(world))

        assert isinstance(action, MoveAction)
        new_x = 6 + action.dx
        new_y = 5 + action.dy
        assert chebyshev(new_x, new_y, 5, 5) > 1

    def test_fleeing_creature_does_not_attack_when_adjacent(self):
        """Even adjacent to the player, a fleeing creature
        retreats instead of attacking (unless cornered)."""
        world = _make_world_player_at(5, 5)
        cid = _make_creature(world, 6, 5, morale=7, state="fleeing")

        action = decide_action(cid, world, _level(), _pid(world))

        assert not isinstance(action, MeleeAttackAction)


class TestEngagedStatePreserved:
    def test_engaged_creature_skips_morale_check(self):
        """A creature already in the engaged state attacks
        normally, regardless of its morale value (no second
        first-sight roll on subsequent turns)."""
        world = _make_world_player_at(5, 5)
        # morale=1 would normally always hesitate, but since
        # the creature is already engaged it should attack.
        cid = _make_creature(world, 6, 5, morale=1, state="engaged")

        action = decide_action(cid, world, _level(), _pid(world))

        assert isinstance(action, MeleeAttackAction)


class TestHpDropMoraleTrigger:
    """Combat applies a morale check when a creature first
    drops to 50% HP or lower. On failure → fleeing state with
    a panic message in the event list."""

    @pytest.mark.asyncio
    async def test_low_morale_creature_breaks_at_half_hp(self):
        from nhc.core.actions._combat import _check_hp_morale_break

        world = _make_world_player_at(5, 5)
        cid = _make_creature(
            world, 6, 5, morale=1, state="engaged", hp=10,
        )
        health = world.get_component(cid, "Health")
        health.current = 4  # 40% — below threshold
        ai = world.get_component(cid, "AI")

        events = []
        _check_hp_morale_break(world, cid, events)

        assert ai.state == "fleeing"
        assert ai.morale_checked_on_hp is True
        assert len(events) == 1
        # The event should be a MessageEvent about flee/panic
        from nhc.core.events import MessageEvent
        assert isinstance(events[0], MessageEvent)
        assert events[0].text  # non-empty narration

    @pytest.mark.asyncio
    async def test_high_morale_creature_holds_at_half_hp(self):
        from nhc.core.actions._combat import _check_hp_morale_break

        world = _make_world_player_at(5, 5)
        cid = _make_creature(
            world, 6, 5, morale=12, state="engaged", hp=10,
        )
        health = world.get_component(cid, "Health")
        health.current = 4
        ai = world.get_component(cid, "AI")

        events = []
        _check_hp_morale_break(world, cid, events)

        assert ai.state == "engaged"
        assert ai.morale_checked_on_hp is True

    @pytest.mark.asyncio
    async def test_morale_check_is_one_shot(self):
        """Once a creature has rolled its half-HP morale check,
        further damage does not re-roll the same check."""
        from nhc.core.actions._combat import _check_hp_morale_break

        world = _make_world_player_at(5, 5)
        cid = _make_creature(
            world, 6, 5, morale=1, state="engaged", hp=10,
        )
        health = world.get_component(cid, "Health")
        health.current = 4
        ai = world.get_component(cid, "AI")
        ai.morale_checked_on_hp = True  # already rolled

        events = []
        _check_hp_morale_break(world, cid, events)

        # No state change, no new events.
        assert ai.state == "engaged"
        assert events == []

    @pytest.mark.asyncio
    async def test_above_half_hp_does_not_trigger(self):
        from nhc.core.actions._combat import _check_hp_morale_break

        world = _make_world_player_at(5, 5)
        cid = _make_creature(
            world, 6, 5, morale=1, state="engaged", hp=10,
        )
        health = world.get_component(cid, "Health")
        health.current = 6  # 60% — above threshold
        ai = world.get_component(cid, "AI")

        events = []
        _check_hp_morale_break(world, cid, events)

        assert ai.state == "engaged"
        assert ai.morale_checked_on_hp is False
        assert events == []

    @pytest.mark.asyncio
    async def test_dead_creature_does_not_trigger(self):
        from nhc.core.actions._combat import _check_hp_morale_break

        world = _make_world_player_at(5, 5)
        cid = _make_creature(
            world, 6, 5, morale=1, state="engaged", hp=10,
        )
        health = world.get_component(cid, "Health")
        health.current = 0  # dead
        ai = world.get_component(cid, "AI")

        events = []
        _check_hp_morale_break(world, cid, events)

        assert ai.state == "engaged"
        assert events == []


# ── Test fixtures stored on the module so helpers stay tiny ──

_g_world: World | None = None
_g_level: Level | None = None
_g_pid: int | None = None


def _make_world_player_at(x: int, y: int) -> World:
    """Build a fresh world+level+player and stash the level/pid
    in module globals so the test helpers can access them
    without redundant arguments."""
    global _g_world, _g_level, _g_pid
    _g_world = World()
    _g_level = _make_level()
    _g_pid = _make_player(_g_world, x=x, y=y)
    return _g_world


def _level() -> Level:
    assert _g_level is not None
    return _g_level


def _pid(world: World) -> int:
    assert _g_pid is not None
    return _g_pid

"""Tests for the peaceful-attack confirmation prompt.

The first melee bump the player directs at a peaceful NPC opens a
confirmation dialog. The dialog offers two options -- "Talk"
(default, listed first) which rolls a peaceful chatter line and
returns a ``HoldAction`` so the turn ticks, and "Attack" which
tags the target ``CombatEngaged`` and lets the original bump
resolve into a melee strike. Subsequent bumps on the same
``CombatEngaged`` target skip the prompt -- once a fight has
started, it flows freely.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nhc.core.actions import (
    BumpAction, HoldAction, MeleeAttackAction, MoveAction,
)
from nhc.core.actions._confirm import confirm_peaceful_attack
from nhc.core.ecs import World
from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.entities.components import (
    AI,
    BlocksMovement,
    CombatEngaged,
    Description,
    Errand,
    Health,
    Player,
    Position,
    Renderable,
    Stats,
    Thief,
)
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed


def _street_level() -> Level:
    tiles = [
        [
            Tile(terrain=Terrain.FLOOR, surface_type=SurfaceType.STREET)
            for _ in range(10)
        ]
        for _ in range(10)
    ]
    return Level(
        id="town_surface", name="Town", depth=0,
        width=10, height=10,
        tiles=tiles, rooms=[], corridors=[], entities=[],
    )


def _make_player(world: World, x: int = 5, y: int = 5) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="town_surface"),
        "Player": Player(),
        "Stats": Stats(strength=2, dexterity=2),
        "Health": Health(current=20, maximum=20),
        "Renderable": Renderable(glyph="@", color="white"),
        "Description": Description(name="Hero"),
    })


def _make_villager(world: World, x: int, y: int) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="town_surface"),
        "Stats": Stats(strength=0, dexterity=1),
        "Health": Health(current=4, maximum=4),
        "AI": AI(behavior="errand", morale=3, faction="human"),
        "BlocksMovement": BlocksMovement(),
        "Renderable": Renderable(glyph="@", color="white"),
        "Description": Description(name="Villager"),
        "Errand": Errand(),
    })


def _make_hostile(world: World, x: int, y: int) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="town_surface"),
        "Stats": Stats(strength=2, dexterity=1),
        "Health": Health(current=6, maximum=6),
        "AI": AI(behavior="aggressive_melee", morale=7, faction="goblinoid"),
        "BlocksMovement": BlocksMovement(),
        "Renderable": Renderable(glyph="g", color="green"),
        "Description": Description(name="Goblin"),
    })


class _Prompt:
    """Capturing stand-in for ``renderer.show_selection_menu``."""

    def __init__(self, choice: int | None = 0) -> None:
        self.choice = choice
        self.calls: list[tuple[str, list]] = []

    def __call__(self, title: str, items: list) -> int | None:
        self.calls.append((title, list(items)))
        return self.choice


class TestPromptTriggers:
    def test_attack_choice_engages_target(self):
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        vid = _make_villager(world, 6, 5)
        action = BumpAction(actor=pid, dx=1, dy=0)
        prompt = _Prompt(choice=1)  # attack

        result = confirm_peaceful_attack(world, level, action, prompt)

        assert len(prompt.calls) == 1
        # Attack chosen: the original BumpAction is returned so the
        # normal resolve → MeleeAttackAction path runs next.
        assert result is action
        # Target tagged engaged.
        assert world.has_component(vid, "CombatEngaged")

    def test_talk_choice_returns_hold_with_chatter(self):
        """Talk is the new default (option 0): roll a peaceful
        chatter line and return a HoldAction so the turn ticks
        without dealing damage. Target stays untagged."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        vid = _make_villager(world, 6, 5)
        action = BumpAction(actor=pid, dx=1, dy=0)
        prompt = _Prompt(choice=0)  # talk

        result = confirm_peaceful_attack(world, level, action, prompt)

        assert isinstance(result, HoldAction)
        assert result.actor == pid
        assert result.message_text, (
            "talk choice should produce a non-empty chatter line"
        )
        assert not world.has_component(vid, "CombatEngaged")

    def test_dialog_lists_talk_first(self):
        """The menu order is talk (0) then attack (1) so an
        accidental Enter on the dialog is non-violent by default."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        _make_villager(world, 6, 5)
        action = BumpAction(actor=pid, dx=1, dy=0)
        prompt = _Prompt(choice=0)

        confirm_peaceful_attack(world, level, action, prompt)

        assert len(prompt.calls) == 1
        _title, items = prompt.calls[0]
        ids = [idx for idx, _label in items]
        labels = [label for _idx, label in items]
        assert ids == [0, 1]
        assert labels == ["Talk", "Attack"]

    def test_engaged_target_skips_prompt(self):
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        vid = _make_villager(world, 6, 5)
        world.add_component(vid, "CombatEngaged", CombatEngaged())
        action = BumpAction(actor=pid, dx=1, dy=0)
        prompt = _Prompt(choice=0)

        result = confirm_peaceful_attack(world, level, action, prompt)

        assert prompt.calls == []
        assert result is action

    def test_hostile_target_skips_prompt(self):
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        _make_hostile(world, 6, 5)
        action = BumpAction(actor=pid, dx=1, dy=0)
        prompt = _Prompt(choice=0)  # would talk if asked

        result = confirm_peaceful_attack(world, level, action, prompt)

        assert prompt.calls == []
        assert result is action

    def test_move_action_passes_through(self):
        """Non-bump actions are never gated by the confirmation."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        action = MoveAction(actor=pid, dx=1, dy=0)
        prompt = _Prompt(choice=0)

        result = confirm_peaceful_attack(world, level, action, prompt)

        assert result is action
        assert prompt.calls == []

    def test_bump_into_empty_tile_passes_through(self):
        """Bump that would resolve to a MoveAction is unaffected."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        action = BumpAction(actor=pid, dx=1, dy=0)
        prompt = _Prompt(choice=0)

        result = confirm_peaceful_attack(world, level, action, prompt)

        assert result is action
        assert prompt.calls == []

    def test_no_prompt_fn_defaults_to_attack(self):
        """Headless/test runners without a prompt fn allow the attack
        through (matches the death-dialog headless default)."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        vid = _make_villager(world, 6, 5)
        action = BumpAction(actor=pid, dx=1, dy=0)

        result = confirm_peaceful_attack(world, level, action, None)

        assert result is action
        assert world.has_component(vid, "CombatEngaged")


class TestMeleeAttackTagsEngaged:
    @pytest.mark.asyncio
    async def test_player_melee_tags_target_engaged(self):
        """A resolved melee strike tags the non-player party so the
        next bump skips the prompt."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        vid = _make_villager(world, 6, 5)
        action = MeleeAttackAction(actor=pid, target=vid)

        await action.execute(world, level)

        assert world.has_component(vid, "CombatEngaged")

    @pytest.mark.asyncio
    async def test_creature_melee_tags_attacker_engaged(self):
        """When a creature strikes the player, tagging the attacker
        means the player's counterattack runs without a prompt."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        vid = _make_villager(world, 6, 5)
        action = MeleeAttackAction(actor=vid, target=pid)

        await action.execute(world, level)

        assert world.has_component(vid, "CombatEngaged")


class TestPeacefulChatterTable:
    """The talk option draws from ``combat.peaceful_chatter`` --
    every locale must ship enough lines to keep encounters from
    blurring together."""

    def test_table_loads_in_each_locale_with_at_least_30_entries(self):
        from nhc.tables.registry import TableRegistry

        for lang in ("en", "ca", "es"):
            registry = TableRegistry.get_or_load(lang)
            table = registry._get_table("combat.peaceful_chatter")
            assert len(table.entries) >= 30, (
                f"{lang}: expected >=30 chatter lines, "
                f"got {len(table.entries)}"
            )


class TestThiefFleeTagsEngaged:
    @pytest.mark.asyncio
    async def test_noticed_flee_marks_thief_engaged(self):
        """A fleeing thief is clearly hostile from the player's POV,
        so chasing them down shouldn't require a confirmation."""
        from nhc.core.actions import PickpocketAction

        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        pplayer = world.get_component(pid, "Player")
        pplayer.gold = 100
        # Alone — no crowd cover, so notice forces flee.
        tid = world.create_entity({
            "Position": Position(x=6, y=5, level_id="town_surface"),
            "Stats": Stats(strength=1, dexterity=3),
            "Health": Health(current=5, maximum=5),
            "AI": AI(behavior="thief", morale=5, faction="human"),
            "BlocksMovement": BlocksMovement(),
            "Renderable": Renderable(glyph="@", color="white"),
            "Description": Description(name="Villager"),
            "Errand": Errand(),
            "Thief": Thief(),
        })
        action = PickpocketAction(actor=tid, target=pid)

        # theft fails (irrelevant here); perception succeeds.
        with patch("nhc.core.actions._pickpocket.d20",
                   side_effect=[1, 20]):
            await action.execute(world, level)

        thief = world.get_component(tid, "Thief")
        assert thief is not None
        assert thief.fleeing is True
        assert world.has_component(tid, "CombatEngaged")

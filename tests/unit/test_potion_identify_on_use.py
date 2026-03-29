"""Tests for potion identification on use (quaff).

When a player quaffs a potion, all potions of the same kind should be
automatically identified — both in inventory and on the floor.
"""

import random

import pytest

from nhc.core.ecs import World
from nhc.core.actions import UseItemAction
from nhc.core.events import ItemUsed
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    Consumable, Description, Equipment, Health, Inventory,
    Player, Position, Renderable, Stats,
)
from nhc.i18n import init as i18n_init
from nhc.rules.identification import ItemKnowledge
from nhc.utils.rng import set_seed


def _make_level(w=10, h=10):
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(w)] for _ in range(h)]
    for row in tiles:
        for tile in row:
            tile.visible = True
    return Level(id="t", name="T", depth=1, width=w, height=h,
                 tiles=tiles, rooms=[], corridors=[], entities=[])


def _make_world_with_player():
    """Create a world with a player entity and return (world, player_id)."""
    w = World()
    pid = w.create_entity({
        "Position": Position(x=5, y=5),
        "Stats": Stats(strength=3, dexterity=3),
        "Health": Health(current=10, maximum=20),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(),
        "Equipment": Equipment(),
        "Description": Description(name="Hero"),
    })
    return w, pid


def _add_disguised_potion(world, knowledge, item_id, player_id=None):
    """Create a disguised potion entity and optionally add to inventory."""
    appearance_name = knowledge.display_name(item_id)
    appearance_short = knowledge.display_short(item_id)
    color = knowledge.glyph_color(item_id)

    components = {
        "Renderable": Renderable(glyph="!", color=color, render_order=1),
        "Description": Description(name=appearance_name, short=appearance_short),
        "Consumable": Consumable(effect="heal", dice="2d4+2"),
        "_potion_id": item_id,
    }

    eid = world.create_entity(components)
    if player_id is not None:
        inv = world.get_component(player_id, "Inventory")
        inv.slots.append(eid)
    return eid


class TestItemUsedEventCarriesItemId:
    """ItemUsed event should carry the real item_id for identification."""

    @pytest.fixture(autouse=True)
    def setup(self):
        set_seed(42)
        i18n_init("en")

    async def test_item_used_carries_item_id(self):
        """ItemUsed events should have item_id set from _potion_id."""
        world, pid = _make_world_with_player()
        knowledge = ItemKnowledge(rng=random.Random(42))
        level = _make_level()

        potion = _add_disguised_potion(
            world, knowledge, "healing_potion", player_id=pid,
        )

        action = UseItemAction(pid, potion)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        item_used = [e for e in events if isinstance(e, ItemUsed)]
        assert len(item_used) == 1
        assert item_used[0].item_id == "healing_potion"


class TestPotionIdentifyOnQuaff:
    """When quaffing a potion, all same-kind potions should be identified."""

    @pytest.fixture(autouse=True)
    def setup(self):
        set_seed(42)
        i18n_init("en")

    async def test_identify_on_quaff_updates_knowledge(self):
        """After quaffing, the potion type should be marked as identified."""
        from unittest.mock import MagicMock
        from nhc.core.game import Game

        game = Game.__new__(Game)
        knowledge = ItemKnowledge(rng=random.Random(42))
        game._knowledge = knowledge
        game.renderer = MagicMock()

        world, pid = _make_world_with_player()
        game.world = world
        game.player_id = pid

        assert not knowledge.is_identified("healing_potion")
        game._identify_potion(real_id="healing_potion")
        assert knowledge.is_identified("healing_potion")

    async def test_identify_updates_all_same_type_in_inventory(self):
        """All potions of same type in inventory should show real name."""
        from unittest.mock import MagicMock
        from nhc.core.game import Game

        game = Game.__new__(Game)
        knowledge = ItemKnowledge(rng=random.Random(42))
        game._knowledge = knowledge
        game.renderer = MagicMock()

        world, pid = _make_world_with_player()
        game.world = world
        game.player_id = pid

        # Add two healing potions to inventory
        p1 = _add_disguised_potion(
            world, knowledge, "healing_potion", player_id=pid,
        )
        p2 = _add_disguised_potion(
            world, knowledge, "healing_potion", player_id=pid,
        )

        # Both should show disguised names
        desc1 = world.get_component(p1, "Description")
        desc2 = world.get_component(p2, "Description")
        assert desc1.name != "Healing Potion"
        assert desc2.name != "Healing Potion"

        # Identify via quaff
        game._identify_potion(real_id="healing_potion")

        # Both should now show real names
        assert desc1.name == "Healing Potion"
        assert desc2.name == "Healing Potion"

    async def test_identify_updates_potions_on_floor(self):
        """Potions on the floor (not in inventory) should also be updated."""
        from unittest.mock import MagicMock
        from nhc.core.game import Game

        game = Game.__new__(Game)
        knowledge = ItemKnowledge(rng=random.Random(42))
        game._knowledge = knowledge
        game.renderer = MagicMock()

        world, pid = _make_world_with_player()
        game.world = world
        game.player_id = pid

        # One on floor (no player_id), one in inventory
        floor_potion = _add_disguised_potion(
            world, knowledge, "healing_potion",
        )
        inv_potion = _add_disguised_potion(
            world, knowledge, "healing_potion", player_id=pid,
        )

        floor_desc = world.get_component(floor_potion, "Description")
        inv_desc = world.get_component(inv_potion, "Description")
        assert floor_desc.name != "Healing Potion"

        game._identify_potion(real_id="healing_potion")

        assert floor_desc.name == "Healing Potion"
        assert inv_desc.name == "Healing Potion"

    async def test_identify_does_not_affect_other_types(self):
        """Identifying healing potions should not reveal strength potions."""
        from unittest.mock import MagicMock
        from nhc.core.game import Game

        game = Game.__new__(Game)
        knowledge = ItemKnowledge(rng=random.Random(42))
        game._knowledge = knowledge
        game.renderer = MagicMock()

        world, pid = _make_world_with_player()
        game.world = world
        game.player_id = pid

        _add_disguised_potion(
            world, knowledge, "healing_potion", player_id=pid,
        )
        strength_potion = _add_disguised_potion(
            world, knowledge, "potion_strength", player_id=pid,
        )
        # Override effect for strength potion
        cons = world.get_component(strength_potion, "Consumable")
        cons.effect = "strength"

        strength_desc = world.get_component(strength_potion, "Description")
        original_name = strength_desc.name

        game._identify_potion(real_id="healing_potion")

        # Strength potion should still be disguised
        assert strength_desc.name == original_name
        assert not knowledge.is_identified("potion_strength")

    async def test_already_identified_is_noop(self):
        """Identifying an already identified type should be a no-op."""
        from unittest.mock import MagicMock
        from nhc.core.game import Game

        game = Game.__new__(Game)
        knowledge = ItemKnowledge(rng=random.Random(42))
        game._knowledge = knowledge
        game.renderer = MagicMock()

        world, pid = _make_world_with_player()
        game.world = world
        game.player_id = pid

        knowledge.identify("healing_potion")
        game._identify_potion(real_id="healing_potion")
        # Should not crash or double-message
        game.renderer.add_message.assert_not_called()

"""Tests for action resolution."""

import pytest

from nhc.core.actions import (
    BumpAction,
    DescendStairsAction,
    LookAction,
    MeleeAttackAction,
    MoveAction,
    PickupItemAction,
    UseItemAction,
    WaitAction,
)
from nhc.core.ecs import World
from nhc.core.events import CreatureAttacked, CreatureDied, ItemPickedUp, MessageEvent
from nhc.utils.rng import set_seed
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI,
    BlocksMovement,
    Consumable,
    Description,
    Equipment,
    Health,
    Inventory,
    LootTable,
    Player,
    Position,
    Renderable,
    Stats,
    Weapon,
)


def _make_test_level(width=10, height=10):
    """Create a simple floor-only level for testing."""
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(width)]
        for _ in range(height)
    ]
    # Add walls around border
    for x in range(width):
        tiles[0][x].terrain = Terrain.WALL
        tiles[height - 1][x].terrain = Terrain.WALL
    for y in range(height):
        tiles[y][0].terrain = Terrain.WALL
        tiles[y][width - 1].terrain = Terrain.WALL

    return Level(
        id="test", name="Test", depth=1,
        width=width, height=height, tiles=tiles,
    )


def _make_player(world, x=5, y=5):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Health": Health(current=10, maximum=10),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(),
        "Description": Description(name="You"),
        "Equipment": Equipment(),
        "Renderable": Renderable(glyph="@"),
    })


def _make_creature(world, x=6, y=5, hp=4):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=1, dexterity=1),
        "Health": Health(current=hp, maximum=hp),
        "BlocksMovement": BlocksMovement(),
        "Description": Description(name="Goblin"),
        "Renderable": Renderable(glyph="g"),
    })


class TestMoveAction:
    @pytest.mark.asyncio
    async def test_move_updates_position(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)

        action = MoveAction(actor=pid, dx=1, dy=0)
        assert await action.validate(world, level)
        await action.execute(world, level)

        pos = world.get_component(pid, "Position")
        assert pos.x == 6
        assert pos.y == 5

    @pytest.mark.asyncio
    async def test_move_into_wall_invalid(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=1, y=1)

        action = MoveAction(actor=pid, dx=-1, dy=0)  # Into wall at x=0
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_move_blocked_by_creature(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        _make_creature(world, x=6, y=5)

        action = MoveAction(actor=pid, dx=1, dy=0)
        events = await action.execute(world, level)

        # Move should be blocked, position unchanged
        pos = world.get_component(pid, "Position")
        assert pos.x == 5

    @pytest.mark.asyncio
    async def test_open_door_on_bump(self):
        world = World()
        level = _make_test_level()
        level.tiles[5][6].feature = "door_closed"
        pid = _make_player(world, x=5, y=5)

        action = MoveAction(actor=pid, dx=1, dy=0)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        # Door should be open, player stays put (opening costs the move)
        assert level.tiles[5][6].feature == "door_open"
        pos = world.get_component(pid, "Position")
        assert pos.x == 5


class TestPlayerAwareMessages:
    """Test _msg() selects player-perspective message variants."""

    def test_player_attacks_uses_you_variant(self):
        from nhc.core.actions import _msg
        from nhc.i18n import init
        init("en")
        world = World()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=6, y=5)

        result = _msg("combat.hit", world, actor=pid, target=cid, damage=5)
        assert result == "You hit Goblin for 5 damage."

    def test_creature_attacks_player_uses_you_variant(self):
        from nhc.core.actions import _msg
        from nhc.i18n import init
        init("en")
        world = World()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=6, y=5)

        result = _msg("combat.hit", world, actor=cid, target=pid, damage=3)
        assert result == "Goblin hits you for 3 damage."

    def test_creature_vs_creature_uses_default(self):
        from nhc.core.actions import _msg
        from nhc.i18n import init
        init("en")
        world = World()
        c1 = _make_creature(world, x=5, y=5)
        c2 = _make_creature(world, x=6, y=5)

        result = _msg("combat.hit", world, actor=c1, target=c2, damage=2)
        assert result == "Goblin hits Goblin for 2 damage."

    def test_catalan_player_attacks(self):
        from nhc.core.actions import _msg
        from nhc.i18n import init
        init("ca")
        world = World()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=6, y=5)

        result = _msg("combat.hit", world, actor=pid, target=cid, damage=5)
        assert "Colpeges" in result
        assert "goblin" in result.lower()

    def test_catalan_creature_attacks_player(self):
        from nhc.core.actions import _msg
        from nhc.i18n import init
        init("ca")
        world = World()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=6, y=5)

        result = _msg("combat.hit", world, actor=cid, target=pid, damage=3)
        assert "et colpeja" in result
        assert "goblin" in result.lower()

    def test_catalan_article_masculine_consonant(self):
        """Masculine noun starting with consonant gets 'el'."""
        from nhc.core.actions import _msg
        from nhc.i18n import init
        init("ca")
        world = World()
        pid = _make_player(world, x=5, y=5)
        cid = world.create_entity({
            "Position": Position(x=6, y=5),
            "Stats": Stats(strength=1, dexterity=1),
            "Health": Health(current=4, maximum=4),
            "BlocksMovement": BlocksMovement(),
            "Description": Description(name="goblin", gender="m"),
            "Renderable": Renderable(glyph="g"),
        })
        result = _msg("combat.hit", world, actor=cid, target=pid, damage=3)
        assert result.startswith("El goblin")

    def test_catalan_article_masculine_vowel(self):
        """Masculine noun starting with vowel gets l' elision."""
        from nhc.core.actions import _msg
        from nhc.i18n import init
        init("ca")
        world = World()
        pid = _make_player(world, x=5, y=5)
        cid = world.create_entity({
            "Position": Position(x=6, y=5),
            "Stats": Stats(strength=1, dexterity=1),
            "Health": Health(current=4, maximum=4),
            "BlocksMovement": BlocksMovement(),
            "Description": Description(name="esquelet", gender="m"),
            "Renderable": Renderable(glyph="s"),
        })
        result = _msg("combat.hit", world, actor=cid, target=pid, damage=3)
        assert result.startswith("L'esquelet")

    def test_catalan_article_feminine(self):
        """Feminine noun starting with consonant gets 'la'."""
        from nhc.core.actions import _msg
        from nhc.i18n import init
        init("ca")
        world = World()
        pid = _make_player(world, x=5, y=5)
        cid = world.create_entity({
            "Position": Position(x=6, y=5),
            "Stats": Stats(strength=1, dexterity=1),
            "Health": Health(current=4, maximum=4),
            "BlocksMovement": BlocksMovement(),
            "Description": Description(name="rata gegant", gender="f"),
            "Renderable": Renderable(glyph="r"),
        })
        result = _msg("combat.hit", world, actor=cid, target=pid, damage=3)
        assert result.startswith("La rata gegant")

    def test_fallback_when_variant_missing(self):
        from nhc.core.actions import _msg
        from nhc.i18n import init
        init("en")
        world = World()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=6, y=5)

        # shrieker_shriek has no player variant — should use default
        result = _msg("combat.shrieker_shriek", world,
                      actor=pid, creature="Shrieker")
        assert "Shrieker" in result

    def test_corpse_translation(self):
        from nhc.i18n import init, t
        init("ca")
        result = t("combat.corpse", name="Goblin")
        assert result == "cadàver de Goblin"
        init("en")
        result = t("combat.corpse", name="Goblin")
        assert result == "Goblin corpse"


class TestMeleeAttackAction:
    @pytest.mark.asyncio
    async def test_attack_deals_damage(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=6, y=5, hp=20)

        action = MeleeAttackAction(actor=pid, target=cid)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        # Should have attack event
        attack_events = [e for e in events if isinstance(e, CreatureAttacked)]
        assert len(attack_events) == 1

    @pytest.mark.asyncio
    async def test_killing_blow_destroys_entity(self):
        world = World()
        level = _make_test_level()
        # Give player high STR to guarantee kill
        pid = world.create_entity({
            "Position": Position(x=5, y=5),
            "Stats": Stats(strength=20),
            "Health": Health(current=10, maximum=10),
            "Equipment": Equipment(),
            "Description": Description(name="You"),
        })
        cid = _make_creature(world, x=6, y=5, hp=1)

        set_seed(42)  # Avoid natural-1 miss
        action = MeleeAttackAction(actor=pid, target=cid)
        events = await action.execute(world, level)

        death_events = [e for e in events if isinstance(e, CreatureDied)]
        assert len(death_events) == 1
        # Entity should be destroyed
        assert world.get_component(cid, "Health") is None

    @pytest.mark.asyncio
    async def test_attack_non_adjacent_invalid(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=8, y=5)

        action = MeleeAttackAction(actor=pid, target=cid)
        assert not await action.validate(world, level)


class TestPickupItemAction:
    @pytest.mark.asyncio
    async def test_pickup_adds_to_inventory(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Position": Position(x=5, y=5),
            "Description": Description(name="Sword"),
            "Weapon": Weapon(damage="1d8"),
        })

        action = PickupItemAction(actor=pid, item=item_id)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        inv = world.get_component(pid, "Inventory")
        assert item_id in inv.slots

        pickup_events = [e for e in events if isinstance(e, ItemPickedUp)]
        assert len(pickup_events) == 1

    @pytest.mark.asyncio
    async def test_pickup_auto_equips_weapon(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Position": Position(x=5, y=5),
            "Description": Description(name="Sword"),
            "Weapon": Weapon(damage="1d8"),
        })

        action = PickupItemAction(actor=pid, item=item_id)
        await action.execute(world, level)

        equip = world.get_component(pid, "Equipment")
        assert equip.weapon == item_id

    @pytest.mark.asyncio
    async def test_pickup_full_inventory_invalid(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        inv = world.get_component(pid, "Inventory")
        inv.max_slots = 0  # Full

        item_id = world.create_entity({
            "Position": Position(x=5, y=5),
            "Description": Description(name="Thing"),
        })

        action = PickupItemAction(actor=pid, item=item_id)
        assert not await action.validate(world, level)


class TestBumpAction:
    @pytest.mark.asyncio
    async def test_bump_into_creature_attacks(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=6, y=5, hp=20)

        action = BumpAction(actor=pid, dx=1, dy=0)
        events = await action.execute(world, level)

        attack_events = [e for e in events if isinstance(e, CreatureAttacked)]
        assert len(attack_events) == 1

    @pytest.mark.asyncio
    async def test_bump_into_empty_moves(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)

        action = BumpAction(actor=pid, dx=1, dy=0)
        await action.execute(world, level)

        pos = world.get_component(pid, "Position")
        assert pos.x == 6


class TestDescendStairs:
    @pytest.mark.asyncio
    async def test_descend_on_stairs(self):
        world = World()
        level = _make_test_level()
        level.tiles[5][5].feature = "stairs_down"
        pid = _make_player(world, x=5, y=5)

        action = DescendStairsAction(actor=pid)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        from nhc.core.events import LevelEntered
        level_events = [e for e in events if isinstance(e, LevelEntered)]
        assert len(level_events) == 1
        assert level_events[0].depth == level.depth + 1

    @pytest.mark.asyncio
    async def test_descend_not_on_stairs_invalid(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)

        action = DescendStairsAction(actor=pid)
        assert not await action.validate(world, level)


class TestWaitAction:
    @pytest.mark.asyncio
    async def test_wait_always_valid(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)

        action = WaitAction(actor=pid)
        assert await action.validate(world, level)
        events = await action.execute(world, level)
        assert events == []


class TestLookAction:
    @pytest.mark.asyncio
    async def test_look_nothing_special(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)

        action = LookAction(actor=pid)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("Nothing special" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_look_sees_stairs(self):
        world = World()
        level = _make_test_level()
        level.tiles[5][5].feature = "stairs_down"
        pid = _make_player(world, x=5, y=5)

        action = LookAction(actor=pid)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("stairs" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_look_sees_items(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        world.create_entity({
            "Position": Position(x=5, y=5),
            "Description": Description(
                name="Potion", short="a healing potion",
                long="A bubbling red potion.",
            ),
        })

        action = LookAction(actor=pid)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("bubbling" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_look_sees_visible_creatures(self):
        world = World()
        level = _make_test_level()
        # Mark tiles visible
        for row in level.tiles:
            for tile in row:
                tile.visible = True
        pid = _make_player(world, x=5, y=5)
        world.create_entity({
            "Position": Position(x=6, y=5),
            "AI": AI(behavior="aggressive_melee"),
            "Health": Health(current=4, maximum=4),
            "Description": Description(name="Goblin", short="a goblin"),
            "BlocksMovement": BlocksMovement(),
        })

        action = LookAction(actor=pid)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("goblin" in m for m in msgs)
        assert any("uninjured" in m for m in msgs)


class TestGroundItemAnnouncement:
    @pytest.mark.asyncio
    async def test_move_announces_single_item(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        world.create_entity({
            "Position": Position(x=6, y=5),
            "Description": Description(
                name="Dagger", short="a sharp dagger",
            ),
        })

        action = MoveAction(actor=pid, dx=1, dy=0)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("dagger" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_move_announces_multiple_items(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        world.create_entity({
            "Position": Position(x=6, y=5),
            "Description": Description(name="Dagger"),
        })
        world.create_entity({
            "Position": Position(x=6, y=5),
            "Description": Description(name="Gold"),
        })

        action = MoveAction(actor=pid, dx=1, dy=0)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("2 items" in m for m in msgs)


class TestCorpseAndLoot:
    @pytest.mark.asyncio
    async def test_killing_leaves_corpse(self):
        world = World()
        level = _make_test_level()
        pid = world.create_entity({
            "Position": Position(x=5, y=5),
            "Stats": Stats(strength=20),
            "Health": Health(current=10, maximum=10),
            "Equipment": Equipment(),
            "Description": Description(name="You"),
        })
        cid = world.create_entity({
            "Position": Position(x=6, y=5),
            "Stats": Stats(strength=1, dexterity=1),
            "Health": Health(current=1, maximum=1),
            "BlocksMovement": BlocksMovement(),
            "Description": Description(name="Goblin"),
            "Renderable": Renderable(glyph="g"),
        })

        action = MeleeAttackAction(actor=pid, target=cid)
        events = await action.execute(world, level)

        death_events = [e for e in events if isinstance(e, CreatureDied)]
        assert len(death_events) == 1

        # Check a corpse entity was created at the creature's position
        corpse_found = False
        for eid, rend, pos in world.query("Renderable", "Position"):
            if rend.glyph == "%":
                assert pos.x == 6
                assert pos.y == 5
                corpse_found = True
        assert corpse_found

    @pytest.mark.asyncio
    async def test_killing_with_loot_drops_items(self):
        world = World()
        level = _make_test_level()
        from nhc.entities.registry import EntityRegistry
        EntityRegistry._items["test_loot"] = lambda: {
            "Renderable": Renderable(glyph="!"),
            "Description": Description(name="Loot Item"),
        }

        pid = world.create_entity({
            "Position": Position(x=5, y=5),
            "Stats": Stats(strength=20),
            "Health": Health(current=10, maximum=10),
            "Equipment": Equipment(),
            "Description": Description(name="You"),
        })
        cid = world.create_entity({
            "Position": Position(x=6, y=5),
            "Stats": Stats(strength=1, dexterity=1),
            "Health": Health(current=1, maximum=1),
            "BlocksMovement": BlocksMovement(),
            "Description": Description(name="Goblin"),
            "Renderable": Renderable(glyph="g"),
            "LootTable": LootTable(entries=[("test_loot", 1.0)]),
        })

        from nhc.utils.rng import set_seed
        set_seed(42)

        action = MeleeAttackAction(actor=pid, target=cid)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("drops" in m for m in msgs)

        del EntityRegistry._items["test_loot"]


class TestUseItemAction:
    @pytest.mark.asyncio
    async def test_heal_at_full_hp_refused(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Description": Description(name="Healing Potion"),
            "Consumable": Consumable(effect="heal", dice="2d4"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(item_id)

        action = UseItemAction(actor=pid, item=item_id)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("full health" in m for m in msgs)
        # Item should not be consumed
        assert item_id in inv.slots

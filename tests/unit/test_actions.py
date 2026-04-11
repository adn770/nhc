"""Tests for action resolution."""

import pytest

from nhc.core.actions import (
    BumpAction,
    CloseDoorAction,
    DescendStairsAction,
    LookAction,
    MeleeAttackAction,
    MoveAction,
    PickupItemAction,
    UseItemAction,
    WaitAction,
    _msg,
)
from nhc.core.ecs import World
from nhc.core.events import (
    CreatureAttacked, CreatureDied, ItemPickedUp, LevelEntered, MessageEvent,
)
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
from nhc.entities.registry import EntityRegistry
from nhc.i18n import init, t
from nhc.utils.rng import set_seed


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
        init("en")
        world = World()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=6, y=5)

        result = _msg("combat.hit", world, actor=pid, target=cid, damage=5)
        assert result == "You hit Goblin for 5 damage."

    def test_creature_attacks_player_uses_you_variant(self):
        init("en")
        world = World()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=6, y=5)

        result = _msg("combat.hit", world, actor=cid, target=pid, damage=3)
        assert result == "Goblin hits you for 3 damage."

    def test_creature_vs_creature_uses_default(self):
        init("en")
        world = World()
        c1 = _make_creature(world, x=5, y=5)
        c2 = _make_creature(world, x=6, y=5)

        result = _msg("combat.hit", world, actor=c1, target=c2, damage=2)
        assert result == "Goblin hits Goblin for 2 damage."

    def test_catalan_player_attacks(self):
        init("ca")
        world = World()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=6, y=5)

        result = _msg("combat.hit", world, actor=pid, target=cid, damage=5)
        assert "Colpeges" in result
        assert "goblin" in result.lower()

    def test_catalan_creature_attacks_player(self):
        init("ca")
        world = World()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=6, y=5)

        result = _msg("combat.hit", world, actor=cid, target=pid, damage=3)
        assert "et colpeja" in result
        assert "goblin" in result.lower()

    def test_catalan_article_masculine_consonant(self):
        """Masculine noun starting with consonant gets 'el'."""
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
        init("en")
        world = World()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=6, y=5)

        # shrieker_shriek has no player variant — should use default
        result = _msg("combat.shrieker_shriek", world,
                      actor=pid, creature="Shrieker")
        assert "Shrieker" in result

    def test_corpse_translation(self):
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

    @pytest.mark.asyncio
    async def test_attack_blocked_by_closed_door_west(self):
        """Creature cannot attack through a closed door on the west edge."""
        world = World()
        level = _make_test_level()
        # Player stands on door tile at (5,5), door is on the west edge
        level.tiles[5][5].feature = "door_closed"
        level.tiles[5][5].door_side = "west"
        pid = _make_player(world, x=5, y=5)
        # Creature is to the west at (4,5) — on the other side of the door
        cid = _make_creature(world, x=4, y=5)

        action = MeleeAttackAction(actor=pid, target=cid)
        assert not await action.validate(world, level)

        # Attack from creature side should also be blocked
        action2 = MeleeAttackAction(actor=cid, target=pid)
        assert not await action2.validate(world, level)

    @pytest.mark.asyncio
    async def test_attack_blocked_by_closed_door_other_sides(self):
        """Closed doors block attacks on all cardinal sides."""
        for door_side, creature_dx, creature_dy in [
            ("east", 1, 0),
            ("north", 0, -1),
            ("south", 0, 1),
        ]:
            world = World()
            level = _make_test_level()
            level.tiles[5][5].feature = "door_closed"
            level.tiles[5][5].door_side = door_side
            pid = _make_player(world, x=5, y=5)
            cid = _make_creature(world, x=5 + creature_dx, y=5 + creature_dy)

            action = MeleeAttackAction(actor=cid, target=pid)
            assert not await action.validate(world, level), \
                f"Attack should be blocked by closed door on {door_side}"

    @pytest.mark.asyncio
    async def test_attack_allowed_through_open_door(self):
        """Open doors do not block melee attacks."""
        world = World()
        level = _make_test_level()
        level.tiles[5][5].feature = "door_open"
        level.tiles[5][5].door_side = "west"
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=4, y=5)

        action = MeleeAttackAction(actor=cid, target=pid)
        assert await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_attack_allowed_same_side_of_closed_door(self):
        """Entities on the same side of a closed door can still attack."""
        world = World()
        level = _make_test_level()
        # Door on west edge — east side is the "room" side
        level.tiles[5][5].feature = "door_closed"
        level.tiles[5][5].door_side = "west"
        pid = _make_player(world, x=5, y=5)
        # Creature to the east — same side as player (not blocked)
        cid = _make_creature(world, x=6, y=5)

        action = MeleeAttackAction(actor=cid, target=pid)
        assert await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_attack_blocked_by_locked_door(self):
        """Locked doors also block melee attacks."""
        world = World()
        level = _make_test_level()
        level.tiles[5][5].feature = "door_locked"
        level.tiles[5][5].door_side = "west"
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=4, y=5)

        action = MeleeAttackAction(actor=cid, target=pid)
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
    async def test_pickup_does_not_auto_equip(self):
        """Weapons must be manually equipped with 'e' key."""
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
        assert equip.weapon is None

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


    @pytest.mark.asyncio
    async def test_pickup_removes_position_component(self):
        """Picked-up items must have Position fully removed, not
        set to None — otherwise tick_doors crashes iterating
        entities with Position."""
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Position": Position(x=5, y=5),
            "Description": Description(name="Potion"),
        })

        action = PickupItemAction(actor=pid, item=item_id)
        await action.execute(world, level)

        assert not world.has_component(item_id, "Position"), (
            "Position component should be removed, not set to None"
        )
        # Verify the item doesn't appear in Position queries
        positions = world.query("Position")
        eids = [eid for eid, _ in positions]
        assert item_id not in eids


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

    @pytest.mark.asyncio
    async def test_move_announces_gold_amount(self):
        """Gold sightings show the actual coin count, not 'a pile'."""
        init("en")
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        world.create_entity({
            "Position": Position(x=6, y=5),
            "Description": Description(
                name="47 Gold", short="a pile of gold coins",
            ),
            "Gold": True,
        })

        action = MoveAction(actor=pid, dx=1, dy=0)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        # Amount present, generic "pile" wording replaced
        assert any("47" in m for m in msgs)
        assert not any("pile of gold coins" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_move_announces_single_gold_coin(self):
        """Amount of 1 uses singular form."""
        init("en")
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        world.create_entity({
            "Position": Position(x=6, y=5),
            "Description": Description(
                name="1 Gold", short="a pile of gold coins",
            ),
            "Gold": True,
        })

        action = MoveAction(actor=pid, dx=1, dy=0)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("1 gold coin" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_move_stacks_identical_corpses(self):
        """Three identical corpses report as a single pluralized entry."""
        init("en")
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        for _ in range(3):
            world.create_entity({
                "Position": Position(x=6, y=5),
                "Description": Description(
                    name="Goblin corpse",
                    short="Goblin corpse",
                    plural="Goblin corpses",
                ),
            })

        action = MoveAction(actor=pid, dx=1, dy=0)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        # Single stack collapses to see_item form with plural label
        assert any("3 Goblin corpses" in m for m in msgs)
        # Should NOT spell out three separate entries
        assert not any("Goblin corpse, Goblin corpse" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_move_stacks_mixed_items(self):
        """Mixed stacks: 2 corpses + 1 dagger -> 'You see 3 items'."""
        init("en")
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        for _ in range(2):
            world.create_entity({
                "Position": Position(x=6, y=5),
                "Description": Description(
                    name="Goblin corpse",
                    short="Goblin corpse",
                    plural="Goblin corpses",
                ),
            })
        world.create_entity({
            "Position": Position(x=6, y=5),
            "Description": Description(
                name="Dagger", short="a sharp dagger",
            ),
        })

        action = MoveAction(actor=pid, dx=1, dy=0)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        # Total item count is 3, distributed across 2 stacks
        joined = " ".join(msgs)
        assert "3 items" in joined
        assert "2 Goblin corpses" in joined
        assert "a sharp dagger" in joined

    @pytest.mark.asyncio
    async def test_move_stacks_single_item_no_plural_field(self):
        """One item without a plural field renders unchanged."""
        init("en")
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
        assert any("a sharp dagger" in m for m in msgs)


class TestLookActionStacking:
    @pytest.mark.asyncio
    async def test_look_stacks_identical_corpses(self):
        """LookAction also collapses identical items into a stacked label."""
        init("en")
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        for _ in range(3):
            world.create_entity({
                "Position": Position(x=5, y=5),
                "Description": Description(
                    name="Goblin corpse",
                    short="Goblin corpse",
                    plural="Goblin corpses",
                ),
            })

        action = LookAction(actor=pid)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        joined = " ".join(msgs)
        assert "3 Goblin corpses" in joined
        # Three discrete corpse messages would mean 3 occurrences of "corpse"
        # without the count prefix; verify only the stacked form appears.
        assert joined.count("Goblin corpses") == 1


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

        set_seed(42)

        action = MeleeAttackAction(actor=pid, target=cid)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("drops" in m for m in msgs)

        del EntityRegistry._items["test_loot"]


class TestUseItemAction:
    @pytest.mark.asyncio
    async def test_heal_at_full_hp_consumes_item(self):
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
        # Item should still be consumed (and identified)
        assert item_id not in inv.slots


class TestCloseDoorAction:
    @pytest.mark.asyncio
    async def test_close_open_door(self):
        init("en")
        world = World()
        level = _make_test_level()
        level.tiles[5][6].feature = "door_open"
        level.tiles[5][6].opened_at_turn = 3
        pid = _make_player(world, x=5, y=5)

        action = CloseDoorAction(actor=pid, dx=1, dy=0)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        assert level.tiles[5][6].feature == "door_closed"
        assert level.tiles[5][6].opened_at_turn is None
        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("close" in m.lower() for m in msgs)

    @pytest.mark.asyncio
    async def test_validate_rejects_closed_door(self):
        world = World()
        level = _make_test_level()
        level.tiles[5][6].feature = "door_closed"
        pid = _make_player(world, x=5, y=5)

        action = CloseDoorAction(actor=pid, dx=1, dy=0)
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_validate_rejects_empty_tile(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)

        action = CloseDoorAction(actor=pid, dx=1, dy=0)
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_validate_rejects_out_of_bounds(self):
        world = World()
        level = _make_test_level(width=10, height=10)
        pid = _make_player(world, x=1, y=1)

        action = CloseDoorAction(actor=pid, dx=-5, dy=0)
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_validate_rejects_when_creature_blocks_door(self):
        """Can't close a door while another creature stands on it."""
        world = World()
        level = _make_test_level()
        level.tiles[5][6].feature = "door_open"
        pid = _make_player(world, x=5, y=5)
        _make_creature(world, x=6, y=5)

        action = CloseDoorAction(actor=pid, dx=1, dy=0)
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_close_own_tile_door(self):
        """A player standing on an open door can close it in place."""
        init("en")
        world = World()
        level = _make_test_level()
        level.tiles[5][5].feature = "door_open"
        level.tiles[5][5].opened_at_turn = 1
        pid = _make_player(world, x=5, y=5)

        action = CloseDoorAction(actor=pid, dx=0, dy=0)
        assert await action.validate(world, level)
        await action.execute(world, level)

        assert level.tiles[5][5].feature == "door_closed"

    @pytest.mark.asyncio
    async def test_find_close_door_action_finds_adjacent(self):
        """game_input.find_close_door_action returns CloseDoorAction for
        an adjacent open door."""
        from nhc.core import game_input

        world = World()
        level = _make_test_level()
        level.tiles[5][6].feature = "door_open"
        pid = _make_player(world, x=5, y=5)

        class _FakeRenderer:
            def add_message(self, msg):
                self.msg = msg

        class _FakeGame:
            pass

        game = _FakeGame()
        game.world = world
        game.level = level
        game.player_id = pid
        game.renderer = _FakeRenderer()

        action = game_input.find_close_door_action(game)
        assert isinstance(action, CloseDoorAction)
        assert (action.dx, action.dy) == (1, 0)

    @pytest.mark.asyncio
    async def test_find_close_door_action_none_when_missing(self):
        from nhc.core import game_input

        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)

        class _FakeRenderer:
            def __init__(self):
                self.messages = []

            def add_message(self, msg):
                self.messages.append(msg)

        class _FakeGame:
            pass

        game = _FakeGame()
        game.world = world
        game.level = level
        game.player_id = pid
        game.renderer = _FakeRenderer()

        action = game_input.find_close_door_action(game)
        assert action is None
        assert game.renderer.messages  # user feedback

    def _make_dig_game(self, target_terrain):
        """Build a minimal game with a digging tool equipped and the
        target tile east of the player set to *target_terrain*."""
        from nhc.core import game_input  # noqa: F401
        from nhc.entities.components import (
            DiggingTool, Equipment, Inventory, Weapon,
        )

        world = World()
        level = _make_test_level()
        level.tiles[5][6] = Tile(terrain=target_terrain)
        pid = _make_player(world, x=5, y=5)
        # Equip a digging tool
        tool = world.create_entity({
            "Description": Description(name="Pick"),
            "Weapon": Weapon(damage="1d4", type="melee", slots=1),
            "DiggingTool": DiggingTool(bonus=0),
        })
        inv = world.get_component(pid, "Inventory") or Inventory(max_slots=8)
        if world.get_component(pid, "Inventory") is None:
            world.add_component(pid, inv)
        inv.slots.append(tool)
        equip = world.get_component(pid, "Equipment") or Equipment()
        if world.get_component(pid, "Equipment") is None:
            world.add_component(pid, equip)
        equip.weapon = tool

        class _FakeRenderer:
            def __init__(self):
                self.messages = []

            def add_message(self, msg):
                self.messages.append(msg)

        class _FakeGame:
            pass

        game = _FakeGame()
        game.world = world
        game.level = level
        game.player_id = pid
        game.renderer = _FakeRenderer()
        return game

    @pytest.mark.asyncio
    async def test_find_dig_action_with_direction_data(self):
        """Autodig: when the client sends data=[dx,dy] the dispatch
        builds a DigAction aimed at that exact tile (no menu)."""
        from nhc.core import game_input
        from nhc.core.actions import DigAction

        game = self._make_dig_game(Terrain.WALL)
        action = game_input.find_dig_action(game, data=[1, 0])
        assert isinstance(action, DigAction)
        assert (action.dx, action.dy) == (1, 0)

    @pytest.mark.asyncio
    async def test_find_dig_action_directed_void(self):
        """Autodig against VOID tiles must also produce a DigAction."""
        from nhc.core import game_input
        from nhc.core.actions import DigAction

        game = self._make_dig_game(Terrain.VOID)
        action = game_input.find_dig_action(game, data=[1, 0])
        assert isinstance(action, DigAction)

    @pytest.mark.asyncio
    async def test_find_dig_action_directed_rejects_floor(self):
        """Directed dig on FLOOR returns None (cannot dig floor)."""
        from nhc.core import game_input

        game = self._make_dig_game(Terrain.FLOOR)
        action = game_input.find_dig_action(game, data=[1, 0])
        assert action is None

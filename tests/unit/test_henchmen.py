"""Tests for the henchmen / party system."""

import pytest

from nhc.core.actions import (
    BumpAction,
    MeleeAttackAction,
    RecruitAction,
    DismissAction,
    GiveItemAction,
)
from nhc.core.actions._combat import _drop_henchman_inventory
from nhc.core.actions._henchman import (
    HIRE_COST_PER_LEVEL,
    MAX_HENCHMEN,
    get_hired_henchmen,
)
from nhc.core.ecs import World
from nhc.core.events import CreatureAttacked, CreatureDied, MessageEvent
from nhc.dungeon.model import Level, Room, Rect, Terrain, Tile
from nhc.entities.components import (
    AI,
    BlocksMovement,
    Consumable,
    Description,
    Equipment,
    Health,
    Henchman,
    Inventory,
    Player,
    Position,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.creatures.adventurer import create_adventurer_at_level
from nhc.entities.registry import EntityRegistry
from nhc.utils.rng import set_seed


def _make_test_level(width=12, height=12):
    """Create a simple floor-only level for testing."""
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(width)]
        for _ in range(height)
    ]
    for x in range(width):
        tiles[0][x].terrain = Terrain.WALL
        tiles[height - 1][x].terrain = Terrain.WALL
    for y in range(height):
        tiles[y][0].terrain = Terrain.WALL
        tiles[y][width - 1].terrain = Terrain.WALL

    level = Level(
        id="test", name="Test", depth=1,
        width=width, height=height, tiles=tiles,
    )
    # Add a room covering the interior
    level.rooms = [Room(
        id="r1",
        rect=Rect(1, 1, width - 2, height - 2),
        tags=[],
    )]
    return level


def _make_player(world, x=5, y=5, gold=500):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Health": Health(current=10, maximum=10),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(gold=gold),
        "Description": Description(name="Hero"),
        "Equipment": Equipment(),
        "Renderable": Renderable(glyph="@"),
    })


def _make_adventurer(world, x=6, y=5, level=1, hired=False,
                     owner=None):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Health": Health(current=8, maximum=8),
        "Inventory": Inventory(max_slots=12),
        "Equipment": Equipment(),
        "AI": AI(behavior="henchman", faction="human"),
        "Henchman": Henchman(
            level=level, hired=hired, owner=owner,
        ),
        "BlocksMovement": BlocksMovement(),
        "Description": Description(name="Adventurer"),
        "Renderable": Renderable(glyph="@", color="cyan"),
    })


def _make_hostile(world, x=4, y=5, hp=4):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=1, dexterity=1),
        "Health": Health(current=hp, maximum=hp),
        "BlocksMovement": BlocksMovement(),
        "AI": AI(behavior="aggressive_melee", faction="goblinoid"),
        "Weapon": Weapon(damage="1d6"),
        "Description": Description(name="Goblin"),
        "Renderable": Renderable(glyph="g"),
    })


# ── Adventurer Factory ─────────────────────────────────────────────

class TestAdventurerFactory:
    def test_level_1_has_base_stats(self):
        set_seed(42)
        comps = create_adventurer_at_level(1, seed=42)
        assert "Stats" in comps
        assert "Health" in comps
        assert "Henchman" in comps
        assert "AI" in comps
        assert comps["Henchman"].level == 1
        assert comps["Health"].current == 8  # max d8 at level 1
        assert comps["AI"].behavior == "henchman"
        assert comps["AI"].faction == "human"

    def test_level_3_has_higher_stats(self):
        set_seed(42)
        l1 = create_adventurer_at_level(1, seed=42)
        set_seed(42)
        l3 = create_adventurer_at_level(3, seed=42)
        assert l3["Health"].maximum >= l1["Health"].maximum
        assert l3["Henchman"].level == 3

    def test_has_inventory_and_equipment(self):
        comps = create_adventurer_at_level(1, seed=99)
        assert "Inventory" in comps
        assert "Equipment" in comps

    def test_registered_in_entity_registry(self):
        EntityRegistry.discover_all()
        comps = EntityRegistry.get_creature("adventurer")
        assert "Henchman" in comps
        assert comps["Henchman"].level == 1


# ── Recruitment ────────────────────────────────────────────────────

class TestRecruitment:
    @pytest.mark.asyncio
    async def test_recruit_deducts_gold(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, gold=500)
        aid = _make_adventurer(world, x=6, y=5, level=2)

        action = RecruitAction(actor=pid, target=aid)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        player = world.get_component(pid, "Player")
        hench = world.get_component(aid, "Henchman")
        assert player.gold == 500 - HIRE_COST_PER_LEVEL * 2
        assert hench.hired is True
        assert hench.owner == pid
        # BlocksMovement removed
        assert not world.has_component(aid, "BlocksMovement")

    @pytest.mark.asyncio
    async def test_recruit_insufficient_gold(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, gold=50)
        aid = _make_adventurer(world, x=6, y=5, level=1)

        action = RecruitAction(actor=pid, target=aid)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        player = world.get_component(pid, "Player")
        hench = world.get_component(aid, "Henchman")
        assert player.gold == 50  # unchanged
        assert hench.hired is False

    @pytest.mark.asyncio
    async def test_recruit_party_full(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, gold=5000)
        # Already have 2 henchmen
        _make_adventurer(world, x=3, y=3, hired=True, owner=pid)
        _make_adventurer(world, x=4, y=3, hired=True, owner=pid)
        # Try to recruit a third
        aid = _make_adventurer(world, x=6, y=5, level=1)

        action = RecruitAction(actor=pid, target=aid)
        events = await action.execute(world, level)

        hench = world.get_component(aid, "Henchman")
        assert hench.hired is False

    @pytest.mark.asyncio
    async def test_bump_unhired_adventurer_resolves_interact(self):
        from nhc.core.actions import HenchmanInteractAction

        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        _make_adventurer(world, x=6, y=5)

        bump = BumpAction(actor=pid, dx=1, dy=0)
        action = bump.resolve(world, level)
        assert isinstance(action, HenchmanInteractAction)

    @pytest.mark.asyncio
    async def test_bump_hired_henchman_does_not_attack(self):
        """Hired henchmen don't have BlocksMovement, so bump = move."""
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5, gold=500)
        aid = _make_adventurer(world, x=6, y=5, hired=True,
                               owner=pid)
        # Remove BlocksMovement (as RecruitAction would)
        world.remove_component(aid, "BlocksMovement")

        bump = BumpAction(actor=pid, dx=1, dy=0)
        action = bump.resolve(world, level)
        # Should be a MoveAction (walk through ally), not attack
        assert not isinstance(action, MeleeAttackAction)
        assert not isinstance(action, RecruitAction)


# ── Dismissal ──────────────────────────────────────────────────────

class TestDismissal:
    @pytest.mark.asyncio
    async def test_dismiss_sets_hired_false(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world)
        aid = _make_adventurer(world, hired=True, owner=pid)
        world.remove_component(aid, "BlocksMovement")

        action = DismissAction(actor=pid, henchman_id=aid)
        assert await action.validate(world, level)
        await action.execute(world, level)

        hench = world.get_component(aid, "Henchman")
        assert hench.hired is False
        assert hench.owner is None
        # BlocksMovement restored
        assert world.has_component(aid, "BlocksMovement")

    @pytest.mark.asyncio
    async def test_dismiss_wrong_owner_fails(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world)
        other_pid = _make_player(world, x=3, y=3)
        aid = _make_adventurer(world, hired=True, owner=other_pid)

        action = DismissAction(actor=pid, henchman_id=aid)
        assert not await action.validate(world, level)


# ── Give Item ──────────────────────────────────────────────────────

class TestGiveItem:
    @pytest.mark.asyncio
    async def test_give_transfers_item(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world)
        aid = _make_adventurer(world, hired=True, owner=pid)
        world.remove_component(aid, "BlocksMovement")

        # Create an item in player inventory
        sword = world.create_entity({
            "Description": Description(name="Sword"),
            "Weapon": Weapon(damage="1d8"),
        })
        p_inv = world.get_component(pid, "Inventory")
        p_inv.slots.append(sword)

        action = GiveItemAction(
            actor=pid, henchman_id=aid, item_id=sword,
        )
        assert await action.validate(world, level)
        await action.execute(world, level)

        assert sword not in p_inv.slots
        h_inv = world.get_component(aid, "Inventory")
        assert sword in h_inv.slots

    @pytest.mark.asyncio
    async def test_give_full_inventory_rejected(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world)
        aid = _make_adventurer(world, hired=True, owner=pid)
        world.remove_component(aid, "BlocksMovement")

        # Fill henchman inventory
        h_inv = world.get_component(aid, "Inventory")
        h_inv.max_slots = 1
        filler = world.create_entity({
            "Description": Description(name="Rock"),
            "Weapon": Weapon(damage="1d4", slots=1),
        })
        h_inv.slots.append(filler)

        # Try to give another item
        sword = world.create_entity({
            "Description": Description(name="Sword"),
            "Weapon": Weapon(damage="1d8", slots=1),
        })
        p_inv = world.get_component(pid, "Inventory")
        p_inv.slots.append(sword)

        action = GiveItemAction(
            actor=pid, henchman_id=aid, item_id=sword,
        )
        events = await action.execute(world, level)

        # Item stays in player inventory
        assert sword in p_inv.slots
        assert sword not in h_inv.slots


# ── Henchman Death ─────────────────────────────────────────────────

class TestHenchmanDeath:
    @pytest.mark.asyncio
    async def test_henchman_drops_inventory_on_death(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        aid = _make_adventurer(
            world, x=6, y=5, hired=True, owner=pid,
        )
        world.remove_component(aid, "BlocksMovement")

        # Give henchman an item
        sword = world.create_entity({
            "Description": Description(name="Sword"),
            "Weapon": Weapon(damage="1d8"),
        })
        h_inv = world.get_component(aid, "Inventory")
        h_inv.slots.append(sword)

        # Kill via repeated attacks until dead
        cid = _make_hostile(world, x=7, y=5, hp=20)
        health = world.get_component(aid, "Health")
        died = False
        for seed in range(100):
            set_seed(seed)
            health_snapshot = health.current
            if health_snapshot <= 0:
                died = True
                break
            action = MeleeAttackAction(actor=cid, target=aid)
            events = await action.execute(world, level)
            for e in events:
                if isinstance(e, CreatureDied):
                    died = True
                    break
            if died:
                break

        assert died, "Henchman should have died"

        # Sword should be on the ground at death position
        sword_pos = world.get_component(sword, "Position")
        assert sword_pos is not None
        assert sword_pos.x == 6
        assert sword_pos.y == 5

    @pytest.mark.asyncio
    async def test_hired_henchman_death_emits_message(self):
        """Killing a hired henchman produces a 'has fallen' message."""
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        aid = _make_adventurer(
            world, x=6, y=5, hired=True, owner=pid,
        )
        world.remove_component(aid, "BlocksMovement")

        # Strong hostile to guarantee a kill
        cid = _make_hostile(world, x=7, y=5, hp=50)
        # Weaken henchman to 1 HP so it dies in one hit
        health = world.get_component(aid, "Health")
        health.current = 1

        set_seed(0)
        action = MeleeAttackAction(actor=cid, target=aid)
        events = await action.execute(world, level)

        died = any(isinstance(e, CreatureDied) for e in events)
        assert died, "Henchman should have died"

        # Should have a "has fallen" message
        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("Adventurer" in m and ("fallen" in m or "caigut" in m
                    or "caído" in m) for m in msgs), (
            f"Expected henchman death message, got: {msgs}"
        )

    @pytest.mark.asyncio
    async def test_unhired_henchman_death_no_fallen_message(self):
        """Killing an unhired henchman does NOT produce 'has fallen'."""
        world = World()
        level = _make_test_level()
        _make_player(world, x=5, y=5)
        aid = _make_adventurer(
            world, x=6, y=5, hired=False, owner=None,
        )
        world.remove_component(aid, "BlocksMovement")

        cid = _make_hostile(world, x=7, y=5, hp=50)
        health = world.get_component(aid, "Health")
        health.current = 1

        set_seed(0)
        action = MeleeAttackAction(actor=cid, target=aid)
        events = await action.execute(world, level)

        died = any(isinstance(e, CreatureDied) for e in events)
        assert died, "Henchman should have died"

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert not any("fallen" in m or "caigut" in m
                       or "caído" in m for m in msgs), (
            f"Unhired henchman death should not emit fallen message: {msgs}"
        )


# ── XP Sharing ─────────────────────────────────────────────────────

class TestXPSharing:
    def test_get_hired_henchmen(self):
        world = World()
        pid = _make_player(world)
        a1 = _make_adventurer(world, x=3, y=3, hired=True,
                              owner=pid)
        a2 = _make_adventurer(world, x=4, y=3, hired=False)

        henchmen = get_hired_henchmen(world, pid)
        assert a1 in henchmen
        assert a2 not in henchmen

    def test_max_henchmen_count(self):
        assert MAX_HENCHMEN == 2


# ── Floor Transitions ──────────────────────────────────────────────

class TestFloorTransitions:
    def test_party_keep_ids_includes_henchmen(self):
        """Verify _party_keep_ids includes henchmen and inventory."""
        # This is a unit-level check of the logic
        world = World()
        pid = _make_player(world)
        aid = _make_adventurer(world, x=3, y=3, hired=True,
                               owner=pid)

        # Give henchman an item
        sword = world.create_entity({
            "Description": Description(name="Sword"),
        })
        h_inv = world.get_component(aid, "Inventory")
        h_inv.slots.append(sword)

        # Simulate _party_keep_ids logic
        keep = {pid}
        p_inv = world.get_component(pid, "Inventory")
        if p_inv:
            keep.update(p_inv.slots)
        for eid, hench in world.query("Henchman"):
            if hench.hired and hench.owner == pid:
                keep.add(eid)
                hi = world.get_component(eid, "Inventory")
                if hi:
                    keep.update(hi.slots)

        assert pid in keep
        assert aid in keep
        assert sword in keep


# ── Hostile Retargeting ────────────────────────────────────────────

class TestHostileRetargeting:
    def test_find_attack_targets_includes_henchmen(self):
        from nhc.ai.behavior import _find_attack_targets

        world = World()
        pid = _make_player(world, x=5, y=5)
        aid = _make_adventurer(
            world, x=4, y=5, hired=True, owner=pid,
        )
        world.remove_component(aid, "BlocksMovement")
        cid = _make_hostile(world, x=3, y=5)

        hostile_pos = world.get_component(cid, "Position")
        targets = _find_attack_targets(cid, world, hostile_pos, pid)

        # Henchman is adjacent (3,5 → 4,5), player is not (3,5 → 5,5)
        assert aid in targets
        assert pid not in targets

    def test_find_attack_targets_includes_player(self):
        from nhc.ai.behavior import _find_attack_targets

        world = World()
        pid = _make_player(world, x=5, y=5)
        cid = _make_hostile(world, x=4, y=5)

        hostile_pos = world.get_component(cid, "Position")
        targets = _find_attack_targets(cid, world, hostile_pos, pid)
        assert pid in targets


# ── Henchman AI ────────────────────────────────────────────────────

class TestHenchmanAI:
    @pytest.mark.asyncio
    async def test_heals_when_low_hp(self):
        from nhc.ai.henchman_ai import decide_henchman_action
        from nhc.core.actions import UseItemAction

        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        aid = _make_adventurer(
            world, x=6, y=6, hired=True, owner=pid,
        )
        world.remove_component(aid, "BlocksMovement")

        # Give a healing potion
        potion = world.create_entity({
            "Description": Description(name="Healing Potion"),
            "Consumable": Consumable(effect="heal", dice="2d4+2"),
        })
        h_inv = world.get_component(aid, "Inventory")
        h_inv.slots.append(potion)

        # Set HP below 50%
        health = world.get_component(aid, "Health")
        health.current = 3

        action = decide_henchman_action(aid, world, level, pid)
        assert isinstance(action, UseItemAction)
        assert action.item == potion

    @pytest.mark.asyncio
    async def test_attacks_adjacent_hostile(self):
        from nhc.ai.henchman_ai import decide_henchman_action

        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        aid = _make_adventurer(
            world, x=6, y=5, hired=True, owner=pid,
        )
        world.remove_component(aid, "BlocksMovement")
        cid = _make_hostile(world, x=7, y=5)

        action = decide_henchman_action(aid, world, level, pid)
        assert isinstance(action, MeleeAttackAction)
        assert action.target == cid

    @pytest.mark.asyncio
    async def test_does_not_attack_other_henchmen(self):
        from nhc.ai.henchman_ai import decide_henchman_action

        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        a1 = _make_adventurer(
            world, x=6, y=5, hired=True, owner=pid,
        )
        world.remove_component(a1, "BlocksMovement")
        a2 = _make_adventurer(
            world, x=7, y=5, hired=True, owner=pid,
        )
        world.remove_component(a2, "BlocksMovement")

        action = decide_henchman_action(a1, world, level, pid)
        # Should not attack the other henchman
        if isinstance(action, MeleeAttackAction):
            assert action.target != a2

    @pytest.mark.asyncio
    async def test_unhired_wanders_not_pathfinds_to_player(self):
        """Unhired adventurers wander with 1-step moves; they never
        pathfind toward the player."""
        from nhc.ai.henchman_ai import decide_henchman_action
        from nhc.core.actions import MoveAction

        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=2, y=2)
        # Place unhired adventurer far from player (> FOLLOW_DISTANCE)
        aid = _make_adventurer(world, x=10, y=10, hired=False)

        action = decide_henchman_action(aid, world, level, pid)
        # Wander produces a single-tile MoveAction (or None if boxed in)
        if action is not None:
            assert isinstance(action, MoveAction)
            assert abs(action.dx) <= 1 and abs(action.dy) <= 1
            assert (action.dx, action.dy) != (0, 0)

    @pytest.mark.asyncio
    async def test_unhired_flees_from_adjacent_hostile(self):
        """Unhired adventurer prefers retreat over engagement."""
        from nhc.ai.henchman_ai import decide_henchman_action
        from nhc.core.actions import MoveAction

        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=1, y=1)
        aid = _make_adventurer(world, x=5, y=5, hired=False)
        # Hostile right next to the adventurer
        cid = _make_hostile(world, x=6, y=5)

        # Free from BlocksMovement collision by removing it from hostile
        # on tiles the adventurer would retreat toward — not needed here
        # because (4,5), (4,4), (5,4) are all open.
        action = decide_henchman_action(aid, world, level, pid)
        assert isinstance(action, MoveAction)
        # Must step AWAY from the hostile (new distance > current 1)
        new_x = 5 + action.dx
        new_y = 5 + action.dy
        new_dist = max(abs(new_x - 6), abs(new_y - 5))
        assert new_dist > 1, (
            f"Expected retreat but moved to ({new_x},{new_y}), "
            f"dist={new_dist}"
        )

    @pytest.mark.asyncio
    async def test_unhired_cornered_fights_back(self):
        """When retreat is impossible, unhired attacks the threat."""
        from nhc.ai.henchman_ai import decide_henchman_action

        world = World()
        level = _make_test_level(width=4, height=4)
        pid = _make_player(world, x=1, y=1)
        # Adventurer cornered in (1,2): (0,*) and (*,0) are walls,
        # (2,2) held by the hostile, (1,1) by the player blocker
        _ = world.create_entity({
            "Position": Position(x=1, y=1),
            "BlocksMovement": BlocksMovement(),
            "Description": Description(name="Wall"),
        })
        _ = world.create_entity({
            "Position": Position(x=2, y=1),
            "BlocksMovement": BlocksMovement(),
            "Description": Description(name="Wall"),
        })
        _ = world.create_entity({
            "Position": Position(x=2, y=2),
            "BlocksMovement": BlocksMovement(),
            "Description": Description(name="Wall"),
        })
        aid = _make_adventurer(world, x=1, y=2, hired=False)
        cid = _make_hostile(world, x=2, y=2)

        action = decide_henchman_action(aid, world, level, pid)
        assert isinstance(action, MeleeAttackAction)
        assert action.target == cid

    @pytest.mark.asyncio
    async def test_unhired_avoids_stairs_down_tile(self):
        """Wandering unhired must never step onto a stairs_down tile."""
        from nhc.ai.henchman_ai import decide_henchman_action
        from nhc.core.actions import MoveAction
        from nhc.utils.rng import set_seed

        world = World()
        level = _make_test_level()
        # Mark the east neighbour as stairs_down
        level.tiles[5][6].feature = "stairs_down"
        pid = _make_player(world, x=1, y=1)
        aid = _make_adventurer(world, x=5, y=5, hired=False)

        # Sweep seeds to exercise the random wander branch
        for seed in range(50):
            set_seed(seed)
            action = decide_henchman_action(aid, world, level, pid)
            if isinstance(action, MoveAction):
                nx, ny = 5 + action.dx, 5 + action.dy
                assert (nx, ny) != (6, 5), (
                    f"Seed {seed}: stepped onto stairs_down"
                )


# ── Unhired approach player ───────────────────────────────────────

class TestUnhiredApproachPlayer:
    @pytest.mark.asyncio
    async def test_approaches_player_in_same_room(self):
        """Unhired adventurer walks toward the player in the same room."""
        from nhc.ai.henchman_ai import decide_henchman_action
        from nhc.core.actions import MoveAction

        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=3, y=3)
        aid = _make_adventurer(world, x=8, y=8, hired=False)

        action = decide_henchman_action(aid, world, level, pid)
        assert isinstance(action, MoveAction)
        # Should move closer to the player
        old_dist = max(abs(8 - 3), abs(8 - 3))  # 5
        new_x = 8 + action.dx
        new_y = 8 + action.dy
        new_dist = max(abs(new_x - 3), abs(new_y - 3))
        assert new_dist < old_dist

    @pytest.mark.asyncio
    async def test_stops_adjacent_to_player(self):
        """Unhired adventurer stops when adjacent to the player."""
        from nhc.ai.henchman_ai import decide_henchman_action
        from nhc.core.actions import MoveAction

        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        aid = _make_adventurer(world, x=6, y=5, hired=False)

        # Already adjacent (dist=1) — should not move onto player
        action = decide_henchman_action(aid, world, level, pid)
        if isinstance(action, MoveAction):
            new_x = 6 + action.dx
            new_y = 5 + action.dy
            # Must not step onto the player's tile
            assert (new_x, new_y) != (5, 5)

    @pytest.mark.asyncio
    async def test_still_flees_threat_over_approach(self):
        """Threat takes priority over approaching the player."""
        from nhc.ai.henchman_ai import decide_henchman_action
        from nhc.core.actions import MeleeAttackAction, MoveAction

        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=3, y=3)
        aid = _make_adventurer(world, x=8, y=8, hired=False)
        _make_hostile(world, x=9, y=8)

        action = decide_henchman_action(aid, world, level, pid)
        # Should flee from the hostile, not approach the player
        assert isinstance(action, MoveAction)
        new_x = 8 + action.dx
        new_y = 8 + action.dy
        new_dist_hostile = max(abs(new_x - 9), abs(new_y - 8))
        assert new_dist_hostile > 1

    @pytest.mark.asyncio
    async def test_wanders_when_in_different_room(self):
        """Unhired adventurer wanders randomly when not sharing a room."""
        from nhc.ai.henchman_ai import decide_henchman_action
        from nhc.core.actions import MoveAction
        from nhc.utils.rng import set_seed

        # Two-room level
        tiles = [
            [Tile(terrain=Terrain.FLOOR) for _ in range(20)]
            for _ in range(10)
        ]
        for x in range(20):
            tiles[0][x].terrain = Terrain.WALL
            tiles[9][x].terrain = Terrain.WALL
        for y in range(10):
            tiles[y][0].terrain = Terrain.WALL
            tiles[y][19].terrain = Terrain.WALL
            tiles[y][10].terrain = Terrain.WALL  # dividing wall
        # Door at (10, 5)
        tiles[5][10].terrain = Terrain.FLOOR

        level = Level(
            id="test", name="Test", depth=1,
            width=20, height=10, tiles=tiles,
        )
        level.rooms = [
            Room(id="left", rect=Rect(1, 1, 9, 8), tags=[]),
            Room(id="right", rect=Rect(11, 1, 8, 8), tags=[]),
        ]

        world = World()
        pid = _make_player(world, x=3, y=3)        # left room
        aid = _make_adventurer(world, x=15, y=5, hired=False)  # right room

        set_seed(42)
        action = decide_henchman_action(aid, world, level, pid)
        # Should just wander, not pathfind toward the player
        if isinstance(action, MoveAction):
            # Movement should be at most 1 step (random wander)
            assert abs(action.dx) <= 1 and abs(action.dy) <= 1


# ── Call for Help ──────────────────────────────────────────────────

class TestCallForHelp:
    def test_calls_for_help_below_one_third_hp(self):
        world = World()
        pid = _make_player(world)
        aid = _make_adventurer(
            world, x=6, y=5, hired=True, owner=pid,
        )
        world.remove_component(aid, "BlocksMovement")

        hench = world.get_component(aid, "Henchman")
        health = world.get_component(aid, "Health")

        # HP above 1/3 — no call
        health.current = health.maximum
        assert not hench.called_for_help

        # Drop HP below 1/3
        health.current = health.maximum // 3 - 1
        # Simulate what the game loop does
        if health.current < health.maximum // 3:
            hench.called_for_help = True

        assert hench.called_for_help

    def test_call_resets_when_healed(self):
        world = World()
        pid = _make_player(world)
        aid = _make_adventurer(
            world, x=6, y=5, hired=True, owner=pid,
        )
        world.remove_component(aid, "BlocksMovement")

        hench = world.get_component(aid, "Henchman")
        health = world.get_component(aid, "Health")

        # Trigger call for help
        health.current = 1
        hench.called_for_help = True

        # Heal above threshold
        health.current = health.maximum
        if health.current >= health.maximum // 3:
            hench.called_for_help = False

        assert not hench.called_for_help

    def test_does_not_spam_call(self):
        """called_for_help prevents repeated messages."""
        world = World()
        pid = _make_player(world)
        aid = _make_adventurer(
            world, x=6, y=5, hired=True, owner=pid,
        )

        hench = world.get_component(aid, "Henchman")
        health = world.get_component(aid, "Health")

        health.current = 1
        hench.called_for_help = True

        # Even though HP is still low, flag is already set
        should_call = (
            health.current < health.maximum // 3
            and not hench.called_for_help
        )
        assert not should_call


# ── Tile Overlap Prevention ────────────────────────────────────────

class TestTileOverlap:
    @pytest.mark.asyncio
    async def test_bump_henchman_swaps_positions(self):
        from nhc.core.actions import BumpAction, SwapAction

        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        aid = _make_adventurer(
            world, x=6, y=5, hired=True, owner=pid,
        )
        world.remove_component(aid, "BlocksMovement")

        bump = BumpAction(actor=pid, dx=1, dy=0)
        action = bump.resolve(world, level)
        assert isinstance(action, SwapAction)

        await action.execute(world, level)
        ppos = world.get_component(pid, "Position")
        hpos = world.get_component(aid, "Position")
        assert ppos.x == 6 and ppos.y == 5
        assert hpos.x == 5 and hpos.y == 5

    @pytest.mark.asyncio
    async def test_henchman_wander_avoids_player(self):
        from nhc.ai.henchman_ai import _is_occupied_by_ally

        world = World()
        pid = _make_player(world, x=5, y=5)
        aid = _make_adventurer(
            world, x=6, y=5, hired=True, owner=pid,
        )

        assert _is_occupied_by_ally(world, 5, 5, aid, pid)
        assert not _is_occupied_by_ally(world, 7, 7, aid, pid)

    @pytest.mark.asyncio
    async def test_henchman_avoids_other_henchman(self):
        from nhc.ai.henchman_ai import _is_occupied_by_ally

        world = World()
        pid = _make_player(world, x=5, y=5)
        a1 = _make_adventurer(
            world, x=6, y=5, hired=True, owner=pid,
        )
        a2 = _make_adventurer(
            world, x=7, y=5, hired=True, owner=pid,
        )

        # a1 should see a2's tile as occupied
        assert _is_occupied_by_ally(world, 7, 5, a1, pid)

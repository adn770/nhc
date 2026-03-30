"""Tests for new scrolls (enchant weapon/armor, charging, teleportation)
and new wands (opening, locking, cold, death, cancellation, digging)."""

import pytest

from nhc.core.actions import UseItemAction, ZapAction
from nhc.core.ecs import World
from nhc.core.events import CreatureDied, MessageEvent
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI,
    Armor,
    BlocksMovement,
    Consumable,
    Description,
    Equipment,
    Health,
    Inventory,
    Player,
    Position,
    Renderable,
    Stats,
    StatusEffect,
    Wand,
    Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed


def _make_level():
    tiles = [[Tile(terrain=Terrain.FLOOR, visible=True) for _ in range(10)]
             for _ in range(10)]
    return Level(id="t", name="T", depth=1, width=10, height=10, tiles=tiles)


def _make_player(world, x=5, y=5, hp=20):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Health": Health(current=hp, maximum=hp),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(xp=30),
        "Description": Description(name="You"),
        "Equipment": Equipment(),
        "Renderable": Renderable(glyph="@"),
    })


def _make_creature(world, x=6, y=5, hp=10, **extra):
    comps = {
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=1, dexterity=1),
        "Health": Health(current=hp, maximum=hp),
        "BlocksMovement": BlocksMovement(),
        "AI": AI(behavior="aggressive_melee"),
        "Description": Description(name="Monster"),
        "Renderable": Renderable(glyph="m"),
    }
    comps.update(extra)
    return world.create_entity(comps)


def _add_scroll(world, player_id, effect, dice="1") -> int:
    item_id = world.create_entity({
        "Consumable": Consumable(effect=effect, dice=dice, slots=1),
        "Description": Description(name="Scroll"),
    })
    inv = world.get_component(player_id, "Inventory")
    inv.slots.append(item_id)
    return item_id


def _add_wand(world, player_id, effect, charges=5) -> int:
    item_id = world.create_entity({
        "Wand": Wand(effect=effect, charges=charges, max_charges=10),
        "Description": Description(name="Wand"),
    })
    inv = world.get_component(player_id, "Inventory")
    inv.slots.append(item_id)
    return item_id


# ── Registry tests ───────────────────────────────────────────────────

NEW_SCROLL_IDS = [
    "scroll_enchant_weapon",
    "scroll_enchant_armor",
    "scroll_charging",
    "scroll_teleportation",
]

NEW_WAND_IDS = [
    "wand_opening",
    "wand_locking",
    "wand_cold",
    "wand_death",
    "wand_cancellation",
    "wand_digging",
]


class TestNewScrollRegistry:
    def setup_method(self):
        EntityRegistry.discover_all()

    @pytest.mark.parametrize("scroll_id", NEW_SCROLL_IDS)
    def test_scroll_loads(self, scroll_id):
        comps = EntityRegistry.get_item(scroll_id)
        assert "Consumable" in comps
        assert "Renderable" in comps
        assert "Description" in comps

    @pytest.mark.parametrize("scroll_id", NEW_SCROLL_IDS)
    def test_scroll_has_effect(self, scroll_id):
        comps = EntityRegistry.get_item(scroll_id)
        assert comps["Consumable"].effect


class TestNewWandRegistry:
    def setup_method(self):
        EntityRegistry.discover_all()

    @pytest.mark.parametrize("wand_id", NEW_WAND_IDS)
    def test_wand_loads(self, wand_id):
        comps = EntityRegistry.get_item(wand_id)
        assert "Wand" in comps
        assert "Renderable" in comps
        assert "Description" in comps

    @pytest.mark.parametrize("wand_id", NEW_WAND_IDS)
    def test_wand_has_effect(self, wand_id):
        comps = EntityRegistry.get_item(wand_id)
        assert comps["Wand"].effect

    @pytest.mark.parametrize("wand_id", NEW_WAND_IDS)
    def test_wand_has_charges(self, wand_id):
        set_seed(42)
        comps = EntityRegistry.get_item(wand_id)
        wand = comps["Wand"]
        assert wand.charges >= 1
        assert wand.charges == wand.max_charges


# ── Scroll of Enchant Weapon ─────────────────────────────────────────

class TestScrollEnchantWeapon:
    def setup_method(self):
        i18n_init("en")

    @pytest.mark.asyncio
    async def test_enchant_weapon_increases_bonus(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        sword = world.create_entity({
            "Weapon": Weapon(damage="1d8", magic_bonus=0),
            "Description": Description(name="Sword"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(sword)
        equip = world.get_component(pid, "Equipment")
        equip.weapon = sword
        item_id = _add_scroll(world, pid, "enchant_weapon")

        await UseItemAction(actor=pid, item=item_id).execute(world, level)

        wpn = world.get_component(sword, "Weapon")
        assert wpn.magic_bonus == 1

    @pytest.mark.asyncio
    async def test_enchant_weapon_caps_at_3(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        sword = world.create_entity({
            "Weapon": Weapon(damage="1d8", magic_bonus=3),
            "Description": Description(name="Sword +3"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(sword)
        equip = world.get_component(pid, "Equipment")
        equip.weapon = sword

        set_seed(1)
        item_id = _add_scroll(world, pid, "enchant_weapon")
        await UseItemAction(actor=pid, item=item_id).execute(world, level)

        # At +3 there's a risk of destruction; bonus should not go above 3
        wpn = world.get_component(sword, "Weapon")
        # Either destroyed (wpn is None) or still +3
        assert wpn is None or wpn.magic_bonus <= 3

    @pytest.mark.asyncio
    async def test_enchant_weapon_no_weapon_equipped(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        item_id = _add_scroll(world, pid, "enchant_weapon")

        events = await UseItemAction(actor=pid, item=item_id).execute(
            world, level,
        )

        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("weapon" in t.lower() for t in texts)


# ── Scroll of Enchant Armor ──────────────────────────────────────────

class TestScrollEnchantArmor:
    def setup_method(self):
        i18n_init("en")

    @pytest.mark.asyncio
    async def test_enchant_armor_increases_bonus(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        plate = world.create_entity({
            "Armor": Armor(slot="body", defense=5, magic_bonus=0),
            "Description": Description(name="Plate Armor"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(plate)
        equip = world.get_component(pid, "Equipment")
        equip.armor = plate
        item_id = _add_scroll(world, pid, "enchant_armor")

        await UseItemAction(actor=pid, item=item_id).execute(world, level)

        arm = world.get_component(plate, "Armor")
        assert arm.magic_bonus == 1

    @pytest.mark.asyncio
    async def test_enchant_armor_caps_at_3(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        plate = world.create_entity({
            "Armor": Armor(slot="body", defense=5, magic_bonus=3),
            "Description": Description(name="Plate +3"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(plate)
        equip = world.get_component(pid, "Equipment")
        equip.armor = plate

        set_seed(1)
        item_id = _add_scroll(world, pid, "enchant_armor")
        await UseItemAction(actor=pid, item=item_id).execute(world, level)

        arm = world.get_component(plate, "Armor")
        assert arm is None or arm.magic_bonus <= 3

    @pytest.mark.asyncio
    async def test_enchant_armor_no_armor_equipped(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        item_id = _add_scroll(world, pid, "enchant_armor")

        events = await UseItemAction(actor=pid, item=item_id).execute(
            world, level,
        )

        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("armor" in t.lower() for t in texts)


# ── Scroll of Charging ───────────────────────────────────────────────

class TestScrollCharging:
    def setup_method(self):
        i18n_init("en")

    @pytest.mark.asyncio
    async def test_charging_restores_wand_charges(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        wand_id = _add_wand(world, pid, "firebolt", charges=2)
        wand = world.get_component(wand_id, "Wand")
        wand.charges = 2  # depleted from max 10
        item_id = _add_scroll(world, pid, "charging", dice="2d6")

        await UseItemAction(actor=pid, item=item_id).execute(world, level)

        wand = world.get_component(wand_id, "Wand")
        assert wand.charges > 2

    @pytest.mark.asyncio
    async def test_charging_no_wand(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        item_id = _add_scroll(world, pid, "charging")

        events = await UseItemAction(actor=pid, item=item_id).execute(
            world, level,
        )

        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("wand" in t.lower() for t in texts)


# ── Scroll of Teleportation ──────────────────────────────────────────

class TestScrollTeleportation:
    def setup_method(self):
        i18n_init("en")

    @pytest.mark.asyncio
    async def test_teleport_moves_player(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        item_id = _add_scroll(world, pid, "teleport")

        set_seed(42)
        await UseItemAction(actor=pid, item=item_id).execute(world, level)

        pos = world.get_component(pid, "Position")
        # Should have moved (extremely unlikely to land on 5,5 again)
        assert (pos.x, pos.y) != (5, 5)

    @pytest.mark.asyncio
    async def test_teleport_lands_on_floor(self):
        world = World()
        tiles = [[Tile(terrain=Terrain.FLOOR, visible=True)
                  for _ in range(10)] for _ in range(10)]
        # Add some walls
        for i in range(5):
            tiles[0][i].terrain = Terrain.WALL
        level = Level(id="t", name="T", depth=1, width=10, height=10,
                      tiles=tiles)
        pid = _make_player(world, x=5, y=5)
        item_id = _add_scroll(world, pid, "teleport")

        set_seed(42)
        await UseItemAction(actor=pid, item=item_id).execute(world, level)

        pos = world.get_component(pid, "Position")
        tile = level.tile_at(pos.x, pos.y)
        assert tile.terrain == Terrain.FLOOR


# ── Wand of Cold ─────────────────────────────────────────────────────

class TestWandCold:
    def setup_method(self):
        i18n_init("en")

    @pytest.mark.asyncio
    async def test_cold_deals_damage(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        mob = _make_creature(world, x=6, y=5, hp=20)
        wand_id = _add_wand(world, pid, "cold")

        await ZapAction(pid, wand_id, mob).execute(world, level)

        hp = world.get_component(mob, "Health")
        assert hp.current < 20

    @pytest.mark.asyncio
    async def test_cold_can_kill(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        mob = _make_creature(world, x=6, y=5, hp=1)
        wand_id = _add_wand(world, pid, "cold")

        events = await ZapAction(pid, wand_id, mob).execute(world, level)

        deaths = [e for e in events if isinstance(e, CreatureDied)]
        assert len(deaths) == 1


# ── Wand of Death ────────────────────────────────────────────────────

class TestWandDeath:
    def setup_method(self):
        i18n_init("en")

    @pytest.mark.asyncio
    async def test_death_kills_creature(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        mob = _make_creature(world, x=6, y=5, hp=100)
        wand_id = _add_wand(world, pid, "death")

        events = await ZapAction(pid, wand_id, mob).execute(world, level)

        deaths = [e for e in events if isinstance(e, CreatureDied)]
        assert len(deaths) == 1

    @pytest.mark.asyncio
    async def test_death_immune_undead(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        mob = _make_creature(world, x=6, y=5, hp=100)
        ai = world.get_component(mob, "AI")
        ai.faction = "undead"
        wand_id = _add_wand(world, pid, "death")

        events = await ZapAction(pid, wand_id, mob).execute(world, level)

        hp = world.get_component(mob, "Health")
        assert hp.current == 100
        deaths = [e for e in events if isinstance(e, CreatureDied)]
        assert len(deaths) == 0


# ── Wand of Cancellation ─────────────────────────────────────────────

class TestWandCancellation:
    def setup_method(self):
        i18n_init("en")

    @pytest.mark.asyncio
    async def test_cancellation_strips_status(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        mob = _make_creature(world, x=6, y=5)
        world.add_component(mob, "StatusEffect",
                            StatusEffect(hasted=5, blessed=3, invisible=4))
        wand_id = _add_wand(world, pid, "cancellation")

        await ZapAction(pid, wand_id, mob).execute(world, level)

        status = world.get_component(mob, "StatusEffect")
        assert status is None or (
            status.hasted == 0 and status.blessed == 0
            and status.invisible == 0
        )

    @pytest.mark.asyncio
    async def test_cancellation_no_effects(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        mob = _make_creature(world, x=6, y=5)
        wand_id = _add_wand(world, pid, "cancellation")

        events = await ZapAction(pid, wand_id, mob).execute(world, level)

        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("no" in t.lower() or "effect" in t.lower() for t in texts)


# ── Wand of Opening ──────────────────────────────────────────────────

class TestWandOpening:
    def setup_method(self):
        i18n_init("en")

    @pytest.mark.asyncio
    async def test_opening_unlocks_door(self):
        world = World()
        tiles = [[Tile(terrain=Terrain.FLOOR, visible=True)
                  for _ in range(10)] for _ in range(10)]
        tiles[5][6].feature = "door_locked"
        tiles[5][6].door_side = "east"
        level = Level(id="t", name="T", depth=1, width=10, height=10,
                      tiles=tiles)
        pid = _make_player(world, x=5, y=5)
        wand_id = _add_wand(world, pid, "opening")
        # Target is the door tile — use a dummy entity at door position
        dummy = _make_creature(world, x=6, y=5)

        events = await ZapAction(pid, wand_id, dummy).execute(world, level)

        assert tiles[5][6].feature == "door_open"


# ── Wand of Locking ──────────────────────────────────────────────────

class TestWandLocking:
    def setup_method(self):
        i18n_init("en")

    @pytest.mark.asyncio
    async def test_locking_locks_door(self):
        world = World()
        tiles = [[Tile(terrain=Terrain.FLOOR, visible=True)
                  for _ in range(10)] for _ in range(10)]
        tiles[5][6].feature = "door_closed"
        tiles[5][6].door_side = "east"
        level = Level(id="t", name="T", depth=1, width=10, height=10,
                      tiles=tiles)
        pid = _make_player(world, x=5, y=5)
        wand_id = _add_wand(world, pid, "locking")
        dummy = _make_creature(world, x=6, y=5)

        events = await ZapAction(pid, wand_id, dummy).execute(world, level)

        assert tiles[5][6].feature == "door_locked"


# ── Wand of Digging ──────────────────────────────────────────────────

class TestWandDigging:
    def setup_method(self):
        i18n_init("en")

    @pytest.mark.asyncio
    async def test_digging_creates_floor(self):
        world = World()
        tiles = [[Tile(terrain=Terrain.FLOOR, visible=True)
                  for _ in range(10)] for _ in range(10)]
        # Wall at (7,5)
        tiles[5][7] = Tile(terrain=Terrain.WALL)
        tiles[5][7].visible = True
        level = Level(id="t", name="T", depth=1, width=10, height=10,
                      tiles=tiles)
        pid = _make_player(world, x=5, y=5)
        wand_id = _add_wand(world, pid, "digging")
        # Target creature is beyond the wall
        dummy = _make_creature(world, x=7, y=5)

        events = await ZapAction(pid, wand_id, dummy).execute(world, level)

        # Wall should be converted to floor
        assert tiles[5][7].terrain == Terrain.FLOOR

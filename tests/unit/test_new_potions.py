"""Tests for new potions: speed, confusion, blindness, acid, sickness."""

import pytest

from nhc.core.actions import ThrowAction, UseItemAction
from nhc.core.ecs import World
from nhc.core.events import ItemUsed, MessageEvent
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI,
    Consumable,
    Description,
    Equipment,
    Health,
    Inventory,
    Player,
    Poison,
    Position,
    Renderable,
    Stats,
    StatusEffect,
    Throwable,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import init as i18n_init
from nhc.rules.identification import POTION_APPEARANCES, POTION_IDS
from nhc.utils.rng import set_seed


def _make_level():
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
             for _ in range(10)]
    for row in tiles:
        for t in row:
            t.visible = True
    return Level(id="t", name="T", depth=1, width=10, height=10,
                 tiles=tiles, rooms=[], corridors=[], entities=[])


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


def _make_creature(world, x=6, y=5, hp=8):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "AI": AI(behavior="aggressive_melee"),
        "Health": Health(current=hp, maximum=hp),
        "Description": Description(name="Goblin"),
        "Renderable": Renderable(glyph="g"),
    })


def _give_potion(world, player, effect, dice="6"):
    pot = world.create_entity({
        "Consumable": Consumable(effect=effect, dice=dice, slots=1),
        "Description": Description(name="Potion"),
        "Throwable": Throwable(),
    })
    world.get_component(player, "Inventory").slots.append(pot)
    return pot


# ── Registration tests ─────────────────────────────────────────────


class TestNewPotionRegistration:
    @pytest.fixture(autouse=True)
    def discover(self):
        EntityRegistry.discover_all()

    def test_potion_speed_registered(self):
        assert "potion_speed" in EntityRegistry.list_items()

    def test_potion_confusion_registered(self):
        assert "potion_confusion" in EntityRegistry.list_items()

    def test_potion_blindness_registered(self):
        assert "potion_blindness" in EntityRegistry.list_items()

    def test_potion_acid_registered(self):
        assert "potion_acid" in EntityRegistry.list_items()

    def test_potion_sickness_registered(self):
        assert "potion_sickness" in EntityRegistry.list_items()


class TestNewPotionFactories:
    @pytest.fixture(autouse=True)
    def discover(self):
        EntityRegistry.discover_all()

    def test_potion_speed_has_consumable(self):
        comps = EntityRegistry.get_item("potion_speed")
        assert "Consumable" in comps
        assert comps["Consumable"].effect == "speed"

    def test_potion_confusion_has_consumable(self):
        comps = EntityRegistry.get_item("potion_confusion")
        assert "Consumable" in comps
        assert comps["Consumable"].effect == "confusion"

    def test_potion_blindness_has_consumable(self):
        comps = EntityRegistry.get_item("potion_blindness")
        assert "Consumable" in comps
        assert comps["Consumable"].effect == "blindness"

    def test_potion_acid_has_consumable(self):
        comps = EntityRegistry.get_item("potion_acid")
        assert "Consumable" in comps
        assert comps["Consumable"].effect == "acid"

    def test_potion_sickness_has_consumable(self):
        comps = EntityRegistry.get_item("potion_sickness")
        assert "Consumable" in comps
        assert comps["Consumable"].effect == "sickness"

    def test_all_new_potions_are_throwable(self):
        for pid in ["potion_speed", "potion_confusion",
                     "potion_blindness", "potion_acid",
                     "potion_sickness"]:
            comps = EntityRegistry.get_item(pid)
            assert "Throwable" in comps, f"{pid} should be throwable"


# ── Identification system ─────────────────────────────────────────


class TestNewPotionIdentification:
    def test_new_potions_in_id_list(self):
        for pid in ["potion_speed", "potion_confusion",
                     "potion_blindness", "potion_acid",
                     "potion_sickness"]:
            assert pid in POTION_IDS, f"{pid} missing from POTION_IDS"

    def test_appearances_match_potion_count(self):
        assert len(POTION_APPEARANCES) >= len(POTION_IDS)


# ── Quaff (UseItemAction) tests ──────────────────────────────────


class TestQuaffPotionSpeed:
    @pytest.mark.asyncio
    async def test_quaff_speed_grants_haste(self):
        i18n_init("en")
        world = World()
        level = _make_level()
        pid = _make_player(world)
        pot = _give_potion(world, pid, "speed", dice="8")

        action = UseItemAction(actor=pid, item=pot)
        await action.execute(world, level)

        status = world.get_component(pid, "StatusEffect")
        assert status is not None
        assert status.hasted == 8


class TestQuaffPotionConfusion:
    @pytest.mark.asyncio
    async def test_quaff_confusion_confuses_self(self):
        """Drinking confusion potion confuses the drinker."""
        i18n_init("en")
        world = World()
        level = _make_level()
        pid = _make_player(world)
        pot = _give_potion(world, pid, "confusion", dice="6")

        action = UseItemAction(actor=pid, item=pot)
        await action.execute(world, level)

        status = world.get_component(pid, "StatusEffect")
        assert status is not None
        assert status.confused == 6


class TestQuaffPotionBlindness:
    @pytest.mark.asyncio
    async def test_quaff_blindness_blinds_self(self):
        """Drinking blindness potion blinds the drinker."""
        i18n_init("en")
        world = World()
        level = _make_level()
        pid = _make_player(world)
        pot = _give_potion(world, pid, "blindness", dice="8")

        action = UseItemAction(actor=pid, item=pot)
        await action.execute(world, level)

        status = world.get_component(pid, "StatusEffect")
        assert status is not None
        assert status.blinded == 8


class TestQuaffPotionAcid:
    @pytest.mark.asyncio
    async def test_quaff_acid_damages_self(self):
        """Drinking acid potion hurts the drinker."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _make_level()
        pid = _make_player(world)
        pot = _give_potion(world, pid, "acid", dice="1d4")

        action = UseItemAction(actor=pid, item=pot)
        await action.execute(world, level)

        health = world.get_component(pid, "Health")
        assert health.current < 10

    @pytest.mark.asyncio
    async def test_quaff_acid_cures_paralysis(self):
        """Acid potion cleanses petrification/paralysis."""
        i18n_init("en")
        world = World()
        level = _make_level()
        pid = _make_player(world)
        world.add_component(
            pid, "StatusEffect", StatusEffect(paralyzed=5))
        pot = _give_potion(world, pid, "acid", dice="1d4")

        action = UseItemAction(actor=pid, item=pot)
        await action.execute(world, level)

        status = world.get_component(pid, "StatusEffect")
        assert status.paralyzed == 0


class TestQuaffPotionSickness:
    @pytest.mark.asyncio
    async def test_quaff_sickness_damages_self(self):
        """Drinking sickness potion deals damage."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _make_level()
        pid = _make_player(world)
        pot = _give_potion(world, pid, "sickness", dice="2d4")

        action = UseItemAction(actor=pid, item=pot)
        await action.execute(world, level)

        health = world.get_component(pid, "Health")
        assert health.current < 10

    @pytest.mark.asyncio
    async def test_quaff_sickness_poisons_self(self):
        """Drinking sickness potion also applies poison."""
        i18n_init("en")
        world = World()
        level = _make_level()
        pid = _make_player(world)
        pot = _give_potion(world, pid, "sickness", dice="2d4")

        action = UseItemAction(actor=pid, item=pot)
        await action.execute(world, level)

        poison = world.get_component(pid, "Poison")
        assert poison is not None
        assert poison.turns_remaining > 0


# ── Throw tests ──────────────────────────────────────────────────


class TestThrowNewPotions:
    @pytest.mark.asyncio
    async def test_throw_confusion_confuses_target(self):
        i18n_init("en")
        world = World()
        level = _make_level()
        pid = _make_player(world)
        mob = _make_creature(world)
        pot = _give_potion(world, pid, "confusion", dice="6")

        await ThrowAction(pid, pot, mob).execute(world, level)

        status = world.get_component(mob, "StatusEffect")
        assert status is not None
        assert status.confused == 6

    @pytest.mark.asyncio
    async def test_throw_blindness_blinds_target(self):
        i18n_init("en")
        world = World()
        level = _make_level()
        pid = _make_player(world)
        mob = _make_creature(world)
        pot = _give_potion(world, pid, "blindness", dice="8")

        await ThrowAction(pid, pot, mob).execute(world, level)

        status = world.get_component(mob, "StatusEffect")
        assert status is not None
        assert status.blinded == 8

    @pytest.mark.asyncio
    async def test_throw_acid_damages_target(self):
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _make_level()
        pid = _make_player(world)
        mob = _make_creature(world, hp=20)
        pot = _give_potion(world, pid, "acid", dice="2d6")

        await ThrowAction(pid, pot, mob).execute(world, level)

        health = world.get_component(mob, "Health")
        assert health.current < 20

    @pytest.mark.asyncio
    async def test_throw_sickness_poisons_target(self):
        i18n_init("en")
        world = World()
        level = _make_level()
        pid = _make_player(world)
        mob = _make_creature(world)
        pot = _give_potion(world, pid, "sickness", dice="2d4")

        await ThrowAction(pid, pot, mob).execute(world, level)

        poison = world.get_component(mob, "Poison")
        assert poison is not None

    @pytest.mark.asyncio
    async def test_throw_speed_hastes_target(self):
        """Throwing speed potion hastes target (buff enemy or ally)."""
        i18n_init("en")
        world = World()
        level = _make_level()
        pid = _make_player(world)
        mob = _make_creature(world)
        pot = _give_potion(world, pid, "speed", dice="8")

        await ThrowAction(pid, pot, mob).execute(world, level)

        status = world.get_component(mob, "StatusEffect")
        assert status is not None
        assert status.hasted == 8


# ── i18n tests ────────────────────────────────────────────────────


class TestNewPotionI18n:
    @pytest.fixture(autouse=True)
    def setup_i18n(self):
        for lang in ("en", "ca", "es"):
            i18n_init(lang)
            yield
            break  # only need to verify en loads without error

    def test_en_names_exist(self):
        from nhc.i18n import t
        i18n_init("en")
        for pid in ["potion_speed", "potion_confusion",
                     "potion_blindness", "potion_acid",
                     "potion_sickness"]:
            name = t(f"items.{pid}.name")
            assert name and not name.startswith("items."), \
                f"Missing en i18n for {pid}"

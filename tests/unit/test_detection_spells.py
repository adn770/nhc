"""Tests for detection spells: detect_magic, detect_evil, detect_gold, detect_food.

Verifies the Detected component system: spells tag entities with a
fading glow, _gather_entities includes detected entities through fog,
and expired detections are cleaned up.
"""

import pytest

from nhc.core.actions import UseItemAction
from nhc.core.ecs import World
from nhc.core.events import ItemUsed, MessageEvent
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI,
    Consumable,
    Detected,
    Description,
    Enchanted,
    Equipment,
    Health,
    Inventory,
    Player,
    Position,
    Renderable,
    Ring,
    Stats,
    Wand,
    Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed


def _make_level(visible=False):
    """10x10 level, all FLOOR. Tiles not visible by default."""
    tiles = [[Tile(terrain=Terrain.FLOOR, visible=visible)
              for _ in range(10)] for _ in range(10)]
    return Level(id="t", name="T", depth=1, width=10, height=10,
                 tiles=tiles, rooms=[], corridors=[], entities=[])


def _make_world(turn=10):
    """World with turn counter set."""
    i18n_init("en")
    set_seed(42)
    w = World()
    w.turn = turn
    return w


def _make_player(world, x=5, y=5):
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="t"),
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Health": Health(current=20, maximum=20),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(),
        "Description": Description(name="Hero"),
        "Equipment": Equipment(),
        "Renderable": Renderable(glyph="@", color="white"),
    })


# ── Detected component ──────────────────────────────────────────────

class TestDetectedComponent:
    def test_defaults(self):
        d = Detected()
        assert d.turn_detected == 0
        assert d.duration == 20
        assert d.glow_color == "#00CCFF"

    def test_custom_values(self):
        d = Detected(turn_detected=5, duration=30, glow_color="#FF0000")
        assert d.turn_detected == 5
        assert d.duration == 30
        assert d.glow_color == "#FF0000"


# ── Detect Magic ─────────────────────────────────────────────────────

class TestDetectMagic:
    @pytest.mark.asyncio
    async def test_detects_consumable(self):
        """Detect magic should tag consumable items with Detected."""
        world = _make_world(turn=10)
        level = _make_level()
        pid = _make_player(world)

        # Place a potion on the map (not visible)
        pot = world.create_entity({
            "Position": Position(x=2, y=2, level_id="t"),
            "Renderable": Renderable(glyph="!", color="red"),
            "Description": Description(name="Potion"),
            "Consumable": Consumable(effect="heal", dice="1d8"),
        })

        scroll = world.create_entity({
            "Renderable": Renderable(glyph="?", color="cyan"),
            "Description": Description(name="Scroll of Detect Magic"),
            "Consumable": Consumable(effect="detect_magic"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(scroll)

        action = UseItemAction(actor=pid, item=scroll)
        events = await action.execute(world, level)

        detected = world.get_component(pot, "Detected")
        assert detected is not None
        assert detected.turn_detected == 10
        assert detected.glow_color == "#00CCFF"

    @pytest.mark.asyncio
    async def test_detects_enchanted_weapon(self):
        """Detect magic should tag enchanted weapons."""
        world = _make_world(turn=5)
        level = _make_level()
        pid = _make_player(world)

        sword = world.create_entity({
            "Position": Position(x=3, y=3, level_id="t"),
            "Renderable": Renderable(glyph=")", color="cyan"),
            "Description": Description(name="Sword +1"),
            "Weapon": Weapon(damage="1d8"),
            "Enchanted": Enchanted(),
        })

        scroll = world.create_entity({
            "Renderable": Renderable(glyph="?", color="cyan"),
            "Description": Description(name="Scroll"),
            "Consumable": Consumable(effect="detect_magic"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(scroll)

        await UseItemAction(actor=pid, item=scroll).execute(world, level)
        assert world.has_component(sword, "Detected")

    @pytest.mark.asyncio
    async def test_detects_ring(self):
        """Detect magic should tag rings."""
        world = _make_world()
        level = _make_level()
        pid = _make_player(world)

        ring = world.create_entity({
            "Position": Position(x=4, y=4, level_id="t"),
            "Renderable": Renderable(glyph="=", color="green"),
            "Description": Description(name="Ring"),
            "Ring": Ring(effect="mending"),
        })

        scroll = world.create_entity({
            "Renderable": Renderable(glyph="?", color="cyan"),
            "Description": Description(name="Scroll"),
            "Consumable": Consumable(effect="detect_magic"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(scroll)

        await UseItemAction(actor=pid, item=scroll).execute(world, level)
        assert world.has_component(ring, "Detected")

    @pytest.mark.asyncio
    async def test_detects_wand(self):
        """Detect magic should tag wands."""
        world = _make_world()
        level = _make_level()
        pid = _make_player(world)

        wand = world.create_entity({
            "Position": Position(x=4, y=4, level_id="t"),
            "Renderable": Renderable(glyph="/", color="green"),
            "Description": Description(name="Wand"),
            "Wand": Wand(effect="firebolt", charges=5, max_charges=10),
        })

        scroll = world.create_entity({
            "Renderable": Renderable(glyph="?", color="cyan"),
            "Description": Description(name="Scroll"),
            "Consumable": Consumable(effect="detect_magic"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(scroll)

        await UseItemAction(actor=pid, item=scroll).execute(world, level)
        assert world.has_component(wand, "Detected")

    @pytest.mark.asyncio
    async def test_ignores_non_magical(self):
        """Non-magical items (gold, plain weapons) not tagged."""
        world = _make_world()
        level = _make_level()
        pid = _make_player(world)

        gold = world.create_entity({
            "Position": Position(x=2, y=2, level_id="t"),
            "Renderable": Renderable(glyph="$", color="yellow"),
            "Description": Description(name="Gold"),
            "Gold": True,
        })

        scroll = world.create_entity({
            "Renderable": Renderable(glyph="?", color="cyan"),
            "Description": Description(name="Scroll"),
            "Consumable": Consumable(effect="detect_magic"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(scroll)

        await UseItemAction(actor=pid, item=scroll).execute(world, level)
        assert not world.has_component(gold, "Detected")


# ── Detect Evil ──────────────────────────────────────────────────────

class TestDetectEvil:
    @pytest.mark.asyncio
    async def test_detects_hostile_creatures(self):
        world = _make_world(turn=7)
        level = _make_level()
        pid = _make_player(world)

        goblin = world.create_entity({
            "Position": Position(x=8, y=8, level_id="t"),
            "Renderable": Renderable(glyph="g", color="green"),
            "Description": Description(name="Goblin"),
            "AI": AI(behavior="aggressive_melee", morale=7,
                     faction="goblinoid"),
            "Health": Health(current=4, maximum=4),
        })

        scroll = world.create_entity({
            "Renderable": Renderable(glyph="?", color="red"),
            "Description": Description(name="Scroll"),
            "Consumable": Consumable(effect="detect_evil"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(scroll)

        await UseItemAction(actor=pid, item=scroll).execute(world, level)

        detected = world.get_component(goblin, "Detected")
        assert detected is not None
        assert detected.glow_color == "#FF3333"
        assert detected.turn_detected == 7


# ── Detect Gold ──────────────────────────────────────────────────────

class TestDetectGold:
    @pytest.mark.asyncio
    async def test_detects_gold(self):
        world = _make_world(turn=15)
        level = _make_level()
        pid = _make_player(world)

        gold = world.create_entity({
            "Position": Position(x=1, y=1, level_id="t"),
            "Renderable": Renderable(glyph="$", color="yellow"),
            "Description": Description(name="Gold"),
            "Gold": True,
        })

        scroll = world.create_entity({
            "Renderable": Renderable(glyph="?", color="yellow"),
            "Description": Description(name="Scroll"),
            "Consumable": Consumable(effect="detect_gold"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(scroll)

        await UseItemAction(actor=pid, item=scroll).execute(world, level)

        detected = world.get_component(gold, "Detected")
        assert detected is not None
        assert detected.glow_color == "#FFD700"

    @pytest.mark.asyncio
    async def test_ignores_non_gold(self):
        world = _make_world()
        level = _make_level()
        pid = _make_player(world)

        pot = world.create_entity({
            "Position": Position(x=2, y=2, level_id="t"),
            "Renderable": Renderable(glyph="!", color="red"),
            "Description": Description(name="Potion"),
            "Consumable": Consumable(effect="heal"),
        })

        scroll = world.create_entity({
            "Renderable": Renderable(glyph="?", color="yellow"),
            "Description": Description(name="Scroll"),
            "Consumable": Consumable(effect="detect_gold"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(scroll)

        await UseItemAction(actor=pid, item=scroll).execute(world, level)
        assert not world.has_component(pot, "Detected")


# ── Detect Food ──────────────────────────────────────────────────────

class TestDetectFood:
    @pytest.mark.asyncio
    async def test_detects_food(self):
        world = _make_world(turn=12)
        level = _make_level()
        pid = _make_player(world)

        apple = world.create_entity({
            "Position": Position(x=3, y=3, level_id="t"),
            "Renderable": Renderable(glyph="(", color="green"),
            "Description": Description(name="Apple"),
            "Consumable": Consumable(effect="satiate", dice="200"),
        })

        scroll = world.create_entity({
            "Renderable": Renderable(glyph="?", color="green"),
            "Description": Description(name="Scroll"),
            "Consumable": Consumable(effect="detect_food"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(scroll)

        await UseItemAction(actor=pid, item=scroll).execute(world, level)

        detected = world.get_component(apple, "Detected")
        assert detected is not None
        assert detected.glow_color == "#33FF33"

    @pytest.mark.asyncio
    async def test_ignores_non_food_consumable(self):
        """Healing potions are not food."""
        world = _make_world()
        level = _make_level()
        pid = _make_player(world)

        pot = world.create_entity({
            "Position": Position(x=2, y=2, level_id="t"),
            "Renderable": Renderable(glyph="!", color="red"),
            "Description": Description(name="Potion"),
            "Consumable": Consumable(effect="heal"),
        })

        scroll = world.create_entity({
            "Renderable": Renderable(glyph="?", color="green"),
            "Description": Description(name="Scroll"),
            "Consumable": Consumable(effect="detect_food"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(scroll)

        await UseItemAction(actor=pid, item=scroll).execute(world, level)
        assert not world.has_component(pot, "Detected")


# ── _gather_entities with Detected ───────────────────────────────────

class TestGatherEntitiesDetected:
    def _make_renderer(self):
        from nhc.rendering.web_client import WebClient
        # Create a minimal WebClient (needs a _send callable)
        renderer = WebClient.__new__(WebClient)
        renderer._last_fov = set()
        renderer._last_walk = set()
        renderer._out_queue = None
        renderer.messages = []
        renderer.floor_svg = None
        renderer.floor_svg_id = None
        return renderer

    def test_includes_detected_on_non_visible_tile(self):
        """Detected entities appear in state even if tile not visible."""
        world = _make_world(turn=10)
        level = _make_level(visible=False)  # all tiles not visible

        pid = _make_player(world)
        # Make player tile visible so player is included
        level.tile_at(5, 5).visible = True

        pot = world.create_entity({
            "Position": Position(x=2, y=2, level_id="t"),
            "Renderable": Renderable(glyph="!", color="red"),
            "Description": Description(name="Potion"),
            "Detected": Detected(turn_detected=8, duration=20,
                                 glow_color="#00CCFF"),
        })

        renderer = self._make_renderer()
        entities = renderer._gather_entities(world, level, pid, turn=10)

        ids = {e["id"] for e in entities}
        assert pot in ids

        pot_entry = next(e for e in entities if e["id"] == pot)
        assert pot_entry["detected"] is True
        assert pot_entry["glow_color"] == "#00CCFF"
        assert 0.0 < pot_entry["glow_alpha"] <= 1.0

    def test_excludes_expired_detected(self):
        """Detected entities whose duration has elapsed are excluded."""
        world = _make_world(turn=50)
        level = _make_level(visible=False)
        pid = _make_player(world)
        level.tile_at(5, 5).visible = True

        pot = world.create_entity({
            "Position": Position(x=2, y=2, level_id="t"),
            "Renderable": Renderable(glyph="!", color="red"),
            "Description": Description(name="Potion"),
            "Detected": Detected(turn_detected=10, duration=20,
                                 glow_color="#00CCFF"),
        })

        renderer = self._make_renderer()
        entities = renderer._gather_entities(world, level, pid, turn=50)

        ids = {e["id"] for e in entities}
        assert pot not in ids
        # Component should be cleaned up
        assert not world.has_component(pot, "Detected")

    def test_glow_alpha_decreases_over_time(self):
        """glow_alpha should decrease as turns pass."""
        world = _make_world(turn=10)
        level = _make_level(visible=False)
        pid = _make_player(world)
        level.tile_at(5, 5).visible = True

        pot = world.create_entity({
            "Position": Position(x=2, y=2, level_id="t"),
            "Renderable": Renderable(glyph="!", color="red"),
            "Detected": Detected(turn_detected=0, duration=20,
                                 glow_color="#00CCFF"),
        })

        renderer = self._make_renderer()
        entities = renderer._gather_entities(world, level, pid, turn=10)
        pot_entry = next(e for e in entities if e["id"] == pot)
        # 10 turns elapsed out of 20 → alpha = 0.5
        assert pot_entry["glow_alpha"] == pytest.approx(0.5, abs=0.01)

    def test_visible_detected_entity_has_flag(self):
        """Entity on visible tile + Detected still gets the glow flag."""
        world = _make_world(turn=5)
        level = _make_level(visible=True)  # all visible
        pid = _make_player(world)

        pot = world.create_entity({
            "Position": Position(x=3, y=3, level_id="t"),
            "Renderable": Renderable(glyph="!", color="red"),
            "Detected": Detected(turn_detected=3, duration=20,
                                 glow_color="#00CCFF"),
        })

        renderer = self._make_renderer()
        entities = renderer._gather_entities(world, level, pid, turn=5)

        pot_entry = next(e for e in entities if e["id"] == pot)
        assert pot_entry["detected"] is True


# ── Scroll factories ─────────────────────────────────────────────────

class TestDetectionScrollFactories:
    @pytest.fixture(autouse=True)
    def _init(self):
        i18n_init("en")
        EntityRegistry.discover_all()

    def test_scroll_detect_gold_exists(self):
        comps = EntityRegistry.get_item("scroll_detect_gold")
        assert "Consumable" in comps
        assert comps["Consumable"].effect == "detect_gold"

    def test_scroll_detect_food_exists(self):
        comps = EntityRegistry.get_item("scroll_detect_food")
        assert "Consumable" in comps
        assert comps["Consumable"].effect == "detect_food"

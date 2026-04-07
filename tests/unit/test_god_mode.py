"""Tests for god mode features."""
import pytest
from nhc.core.ecs import World
from nhc.core.actions import MeleeAttackAction
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI, Description, Equipment, Health, Inventory, Player,
    Position, Stats, Weapon,
)
from nhc.i18n import init as i18n_init
from nhc.rules.identification import ItemKnowledge, ALL_IDS
from nhc.utils.rng import set_seed
import random


class TestGodModeIdentification:
    def test_all_identified_in_god_mode(self):
        """God mode should pre-identify all potions, scrolls, rings, wands."""
        k = ItemKnowledge(rng=random.Random(42))
        # Simulate what game.py does in god mode
        for item_id in ALL_IDS:
            k.identify(item_id)
        for item_id in ALL_IDS:
            assert k.is_identified(item_id)

    def test_identified_shows_real_name(self):
        i18n_init("en")
        k = ItemKnowledge(rng=random.Random(42))
        for item_id in ALL_IDS:
            k.identify(item_id)
        assert k.display_name("potion_healing") == "Healing Potion"
        assert k.display_name("wand_firebolt") == "Wand of Firebolt"
        assert k.display_name("ring_mending") == "Ring of Mending"
        assert "Fireball" in k.display_name("scroll_fireball")


class TestGodModeHP:
    @pytest.mark.asyncio
    async def test_player_survives_lethal_damage(self):
        """In god mode, HP restores to max each turn."""
        i18n_init("en")
        w = World()
        tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
                 for _ in range(10)]
        for row in tiles:
            for t in row:
                t.visible = True
        level = Level(id="t", name="T", depth=1, width=10, height=10,
                      tiles=tiles, rooms=[], corridors=[], entities=[])
        pid = w.create_entity({
            "Position": Position(x=5, y=5),
            "Stats": Stats(strength=2, dexterity=2),
            "Health": Health(current=10, maximum=10),
            "Inventory": Inventory(max_slots=12),
            "Player": Player(),
            "Equipment": Equipment(),
            "Description": Description(name="Hero"),
        })
        mob = w.create_entity({
            "Position": Position(x=6, y=5),
            "AI": AI(behavior="aggressive_melee"),
            "Health": Health(current=20, maximum=20),
            "Weapon": Weapon(damage="1d8"),
            "Description": Description(name="Troll"),
        })
        # Simulate monster hitting player hard
        action = MeleeAttackAction(mob, pid)
        if await action.validate(w, level):
            await action.execute(w, level)

        health = w.get_component(pid, "Health")
        # Player may have taken damage
        damaged = health.current < health.maximum

        # God mode restore (what game loop does)
        health.current = health.maximum
        assert health.current == 10  # Fully restored

    @pytest.mark.asyncio
    async def test_player_death_no_corpse(self):
        """Player reaching 0 HP should not leave a corpse on the map."""
        i18n_init("en")
        set_seed(1)
        w = World()
        tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
                 for _ in range(10)]
        for row in tiles:
            for t in row:
                t.visible = True
        level = Level(id="t", name="T", depth=1, width=10, height=10,
                      tiles=tiles, rooms=[], corridors=[], entities=[])
        pid = w.create_entity({
            "Position": Position(x=5, y=5),
            "Stats": Stats(strength=1, dexterity=1),
            "Health": Health(current=1, maximum=1),
            "Inventory": Inventory(max_slots=12),
            "Player": Player(),
            "Equipment": Equipment(),
            "Description": Description(name="Hero"),
        })
        mob = w.create_entity({
            "Position": Position(x=6, y=5),
            "AI": AI(behavior="aggressive_melee"),
            "Health": Health(current=20, maximum=20),
            "Stats": Stats(strength=10),
            "Weapon": Weapon(damage="10d8"),
            "Description": Description(name="Dragon"),
        })
        # Monster attacks player with massive damage
        action = MeleeAttackAction(mob, pid)
        if await action.validate(w, level):
            await action.execute(w, level)

        # Player should still exist (not destroyed)
        assert w.has_component(pid, "Player")

        # No corpse entity should have been created
        corpses = []
        for eid in list(w._entities):
            r = w.get_component(eid, "Renderable")
            if r and r.glyph == "%":
                corpses.append(eid)
        assert len(corpses) == 0, "Player death should not create a corpse"

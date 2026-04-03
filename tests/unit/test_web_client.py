"""Tests for the WebSocket-based GameClient."""

import asyncio
import json
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from nhc.i18n import init as i18n_init
from nhc.rendering.client import GameClient
from nhc.rendering.web_client import WebClient


@pytest.fixture
def client():
    wc = WebClient(game_mode="classic", lang="ca")
    return wc


def _drain_queue(wc):
    """Get all messages from the output queue as parsed dicts."""
    msgs = []
    while not wc._out_queue.empty():
        msgs.append(json.loads(wc._out_queue.get_nowait()))
    return msgs


def _last_sent(wc):
    """Get the last message from the output queue."""
    msgs = _drain_queue(wc)
    return msgs[-1] if msgs else None


class TestWebClientInterface:
    def test_inherits_game_client(self):
        assert issubclass(WebClient, GameClient)

    def test_initial_state(self):
        wc = WebClient()
        assert wc.game_mode == "classic"
        assert wc.messages == []


class TestWebClientMessages:
    def test_add_message_queues_json(self, client):
        client.add_message("Hello dungeon")
        sent = _last_sent(client)
        assert sent["type"] == "message"
        assert sent["text"] == "Hello dungeon"

    def test_add_message_stores_locally(self, client):
        client.add_message("test")
        assert "test" in client.messages

    def test_message_limit(self, client):
        for i in range(210):
            client.add_message(f"msg {i}")
        assert len(client.messages) == 200


class TestWebClientRender:
    def test_render_queues_state_and_stats(self, client):
        world = MagicMock()
        world._entities = []
        world.get_component = MagicMock(return_value=None)
        level = MagicMock()
        level.height = 0
        level.width = 0
        level.depth = 1
        level.name = "Test"
        client.render(world, level, player_id=1, turn=5)
        msgs = _drain_queue(client)
        types = [m["type"] for m in msgs]
        assert "state" in types
        assert "stats" in types
        state = next(m for m in msgs if m["type"] == "state")
        assert state["turn"] == 5
        # First render sends stats_init (static) + stats (dynamic)
        assert "stats_init" in types
        stats_init = next(m for m in msgs if m["type"] == "stats_init")
        assert "char_name" in stats_init
        stats = next(m for m in msgs if m["type"] == "stats")
        assert "hp" in stats


class TestWebClientEndScreen:
    def test_game_over_queues_json(self, client):
        client.show_end_screen(won=False, turn=42, killed_by="goblin")
        sent = _last_sent(client)
        assert sent["type"] == "game_over"
        assert sent["won"] is False
        assert sent["turn"] == 42
        assert sent["killed_by"] == "goblin"

    def test_victory_queues_json(self, client):
        client.show_end_screen(won=True, turn=99)
        sent = _last_sent(client)
        assert sent["won"] is True


class TestWebClientMenus:
    def test_selection_menu_queues_options(self, client):
        # Put a response in the input queue before calling
        client._in_queue.put('{"type":"menu_select","choice":42}')
        items = [(42, "Sword"), (43, "Shield")]
        result = client.show_selection_menu("Pick one", items)
        sent = _last_sent(client)
        assert sent["type"] == "menu"
        assert sent["title"] == "Pick one"
        assert len(sent["options"]) == 2
        assert result == 42

    def test_selection_menu_cancel(self, client):
        client._in_queue.put('{"type":"cancel"}')
        result = client.show_selection_menu("Pick", [(1, "a")])
        assert result is None


class TestWebClientNarrativeLog:
    """WebClient must expose narrative_log for typed mode."""

    def test_has_narrative_log(self, client):
        assert hasattr(client, "narrative_log")

    def test_add_mechanical_does_not_raise(self, client):
        client.narrative_log.add_mechanical("> attack goblin")

    def test_add_mechanical_typed_mode(self):
        wc = WebClient(game_mode="typed")
        wc.narrative_log.add_mechanical("> look around")


class TestWebClientModeToggle:
    """toggle_mode action from browser is passed through to game."""

    def test_get_input_returns_toggle_mode(self, client):
        client._in_queue.put(json.dumps({
            "type": "action",
            "intent": "toggle_mode",
            "data": None,
        }))

        loop = asyncio.new_event_loop()
        try:
            intent, data = loop.run_until_complete(client.get_input())
        finally:
            loop.close()

        assert intent == "toggle_mode"
        assert data is None

    def test_get_typed_input_returns_toggle_mode(self):
        wc = WebClient(game_mode="typed")
        wc._in_queue.put(json.dumps({
            "type": "action",
            "intent": "toggle_mode",
            "data": None,
        }))

        async def _run():
            wc.render = lambda *a, **kw: None
            return await wc.get_typed_input(
                world=None, level=None, player_id=-1, turn=0,
            )

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_run())
        finally:
            loop.close()

        assert isinstance(result, tuple)
        assert result == ("toggle_mode", None)


class TestWebClientShutdown:
    def test_shutdown_queues_message(self, client):
        client.shutdown()
        sent = _last_sent(client)
        assert sent["type"] == "shutdown"

    def test_initialize_is_noop(self, client):
        client.initialize()  # should not raise


# ── Component stubs for _gather_stats tests ─────────────────────

@dataclass
class _Health:
    current: int = 10
    maximum: int = 10


@dataclass
class _Stats:
    strength: int = 1
    dexterity: int = 1
    constitution: int = 1
    intelligence: int = 1
    wisdom: int = 1
    charisma: int = 1


@dataclass
class _Equipment:
    weapon: int | None = None
    armor: int | None = None
    shield: int | None = None
    helmet: int | None = None
    ring_left: int | None = None
    ring_right: int | None = None


@dataclass
class _Player:
    level: int = 1
    xp: int = 0
    xp_to_next: int = 1000
    gold: int = 0


@dataclass
class _Desc:
    name: str = "?"
    short: str = ""


@dataclass
class _Inventory:
    slots: list = field(default_factory=list)
    max_slots: int = 12


@dataclass
class _Weapon:
    damage: str = "1d6"
    type: str = "melee"
    slots: int = 1
    magic_bonus: int = 0


@dataclass
class _Armor:
    slot: str = "body"
    defense: int = 10
    slots: int = 1
    magic_bonus: int = 0


@dataclass
class _Consumable:
    effect: str = "healing"
    dice: str = "1d6"
    slots: int = 1


@dataclass
class _Wand:
    effect: str = "fire"
    charges: int = 3
    max_charges: int = 10
    recharge_timer: int = 20


@dataclass
class _Ring:
    effect: str = "mending"


@dataclass
class _Throwable:
    pass


def _mock_world(components_by_eid):
    """Build a mock World keyed by (eid, component_name)."""
    world = MagicMock()

    def get_component(eid, name):
        return components_by_eid.get(eid, {}).get(name)

    def has_component(eid, name):
        return name in components_by_eid.get(eid, {})

    world.get_component = MagicMock(side_effect=get_component)
    world.has_component = MagicMock(side_effect=has_component)
    return world


def _mock_level():
    level = MagicMock()
    level.name = "Test"
    level.depth = 1
    return level


def _player_comps(**overrides):
    """Base player component dict."""
    comps = {
        "Health": _Health(),
        "Stats": _Stats(),
        "Equipment": _Equipment(),
        "Player": _Player(),
        "Description": _Desc(name="Hero", short="warrior"),
        "Inventory": _Inventory(),
    }
    comps.update(overrides)
    return comps


def _merged_stats(wc, world, pid, turn, level):
    """Call _gather_stats and merge static + dynamic dicts."""
    static, dynamic = wc._gather_stats(world, pid, turn, level)
    return {**static, **dynamic}


class TestGatherStatsItemMetadata:
    """_gather_stats returns structured item data with type info."""

    def test_items_are_dicts(self):
        pc = _player_comps()
        pc["Inventory"].slots = [10]
        world = _mock_world({
            1: pc,
            10: {"Description": _Desc(name="Healing Potion"),
                 "Consumable": _Consumable()},
        })
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())

        assert len(stats["items"]) == 1
        item = stats["items"][0]
        assert item["id"] == 10
        assert item["name"] == "Healing Potion"
        assert "consumable" in item["types"]
        assert item["equipped"] is False
        assert item["charges"] is None

    def test_weapon_type(self):
        pc = _player_comps()
        pc["Inventory"].slots = [10]
        world = _mock_world({
            1: pc,
            10: {"Description": _Desc(name="Sword"),
                 "Weapon": _Weapon()},
        })
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())
        assert "weapon" in stats["items"][0]["types"]

    def test_armor_slot_types(self):
        pc = _player_comps()
        pc["Inventory"].slots = [10, 11, 12]
        world = _mock_world({
            1: pc,
            10: {"Description": _Desc(name="Chain Mail"),
                 "Armor": _Armor(slot="body")},
            11: {"Description": _Desc(name="Shield"),
                 "Armor": _Armor(slot="shield")},
            12: {"Description": _Desc(name="Helmet"),
                 "Armor": _Armor(slot="helmet")},
        })
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())

        by_name = {i["name"]: i for i in stats["items"]}
        assert "armor" in by_name["Chain Mail"]["types"]
        assert "shield" in by_name["Shield"]["types"]
        assert "helmet" in by_name["Helmet"]["types"]

    def test_wand_type_and_charges(self):
        pc = _player_comps()
        pc["Inventory"].slots = [10]
        world = _mock_world({
            1: pc,
            10: {"Description": _Desc(name="Wand of Fire"),
                 "Wand": _Wand(charges=3, max_charges=10)},
        })
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())

        item = stats["items"][0]
        assert "wand" in item["types"]
        assert item["charges"] == [3, 10]

    def test_ring_type(self):
        pc = _player_comps()
        pc["Inventory"].slots = [10]
        world = _mock_world({
            1: pc,
            10: {"Description": _Desc(name="Ring of Mending"),
                 "Ring": _Ring()},
        })
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())
        assert "ring" in stats["items"][0]["types"]

    def test_throwable_flag(self):
        pc = _player_comps()
        pc["Inventory"].slots = [10]
        world = _mock_world({
            1: pc,
            10: {"Description": _Desc(name="Dagger"),
                 "Weapon": _Weapon(), "Throwable": _Throwable()},
        })
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())

        types = stats["items"][0]["types"]
        assert "weapon" in types
        assert "throwable" in types

    def test_equipped_items_excluded(self):
        """Equipped items appear in line 2, not in items list."""
        pc = _player_comps()
        pc["Equipment"].weapon = 10
        pc["Inventory"].slots = [10, 11]
        world = _mock_world({
            1: pc,
            10: {"Description": _Desc(name="Sword"),
                 "Weapon": _Weapon()},
            11: {"Description": _Desc(name="Potion"),
                 "Consumable": _Consumable()},
        })
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())

        names = [i["name"] for i in stats["items"]]
        assert "Sword" not in names
        assert "Potion" in names

    def test_multiple_types(self):
        pc = _player_comps()
        pc["Inventory"].slots = [10]
        world = _mock_world({
            1: pc,
            10: {"Description": _Desc(name="Potion"),
                 "Consumable": _Consumable(),
                 "Throwable": _Throwable()},
        })
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())

        types = stats["items"][0]["types"]
        assert "consumable" in types
        assert "throwable" in types

    def test_empty_inventory(self):
        world = _mock_world({1: _player_comps()})
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())
        assert stats["items"] == []


class TestActionLabels:
    """_gather_stats includes translated action labels for context menu."""

    def test_action_labels_present(self):
        wc = WebClient(lang="en")
        labels = wc._action_labels()
        for key in ("use", "quaff", "zap", "equip", "unequip",
                     "drop", "throw"):
            assert key in labels, f"missing label for '{key}'"

    def test_action_labels_catalan(self):
        i18n_init("ca")
        wc = WebClient(lang="ca")
        labels = wc._action_labels()
        # Catalan labels should not be the English fallback keys
        assert labels["drop"] != "ui.action_drop"
        assert labels["use"] != "ui.action_use"


class TestItemActionDispatch:
    """get_input handles item_action messages from the client."""

    def test_item_action_returns_intent_and_data(self):
        wc = WebClient(lang="en")
        wc._in_queue.put(json.dumps({
            "type": "item_action",
            "action": "quaff",
            "item_id": 42,
        }))
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(wc.get_input())
        finally:
            loop.close()
        assert result == ("item_action", {"action": "quaff", "item_id": 42})

    def test_item_action_equip(self):
        wc = WebClient(lang="en")
        wc._in_queue.put(json.dumps({
            "type": "item_action",
            "action": "equip",
            "item_id": 10,
        }))
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(wc.get_input())
        finally:
            loop.close()
        assert result == ("item_action", {"action": "equip", "item_id": 10})

    def test_item_action_drop(self):
        wc = WebClient(lang="en")
        wc._in_queue.put(json.dumps({
            "type": "item_action",
            "action": "drop",
            "item_id": 5,
        }))
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(wc.get_input())
        finally:
            loop.close()
        assert result == ("item_action", {"action": "drop", "item_id": 5})


class TestEquippedRingsInStats:
    """Equipped ring names should appear in stats for line 2."""

    def test_ring_names_in_dynamic_stats(self):
        pc = _player_comps()
        pc["Equipment"].ring_left = 20
        pc["Equipment"].ring_right = 21
        pc["Inventory"].slots = [20, 21]
        world = _mock_world({
            1: pc,
            20: {"Description": _Desc(name="Ring of Mending"),
                 "Ring": _Ring(effect="mending")},
            21: {"Description": _Desc(name="Ring of Evasion"),
                 "Ring": _Ring(effect="evasion")},
        })
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())
        assert stats["ring_left_name"] == "Ring of Mending"
        assert stats["ring_right_name"] == "Ring of Evasion"

    def test_no_rings_empty_names(self):
        world = _mock_world({1: _player_comps()})
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())
        assert stats["ring_left_name"] == ""
        assert stats["ring_right_name"] == ""

    def test_single_ring_equipped(self):
        pc = _player_comps()
        pc["Equipment"].ring_left = 20
        pc["Inventory"].slots = [20]
        world = _mock_world({
            1: pc,
            20: {"Description": _Desc(name="Ring of Protection"),
                 "Ring": _Ring(effect="protection")},
        })
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())
        assert stats["ring_left_name"] == "Ring of Protection"
        assert stats["ring_right_name"] == ""


class TestEquippedItemsNotInInventoryLine:
    """Equipped items should not appear in the items list (line 3)."""

    def test_equipped_weapon_excluded_from_items(self):
        pc = _player_comps()
        pc["Equipment"].weapon = 10
        pc["Inventory"].slots = [10, 11]
        world = _mock_world({
            1: pc,
            10: {"Description": _Desc(name="Sword"),
                 "Weapon": _Weapon()},
            11: {"Description": _Desc(name="Potion"),
                 "Consumable": _Consumable()},
        })
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())
        names = [i["name"] for i in stats["items"]]
        assert "Sword" not in names
        assert "Potion" in names

    def test_equipped_ring_excluded_from_items(self):
        pc = _player_comps()
        pc["Equipment"].ring_left = 20
        pc["Inventory"].slots = [20, 11]
        world = _mock_world({
            1: pc,
            20: {"Description": _Desc(name="Ring of Mending"),
                 "Ring": _Ring()},
            11: {"Description": _Desc(name="Potion"),
                 "Consumable": _Consumable()},
        })
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())
        names = [i["name"] for i in stats["items"]]
        assert "Ring of Mending" not in names
        assert "Potion" in names

    def test_equipped_armor_excluded_from_items(self):
        pc = _player_comps()
        pc["Equipment"].armor = 10
        pc["Equipment"].shield = 11
        pc["Equipment"].helmet = 12
        pc["Inventory"].slots = [10, 11, 12, 13]
        world = _mock_world({
            1: pc,
            10: {"Description": _Desc(name="Chain Mail"),
                 "Armor": _Armor(slot="body")},
            11: {"Description": _Desc(name="Shield"),
                 "Armor": _Armor(slot="shield")},
            12: {"Description": _Desc(name="Helmet"),
                 "Armor": _Armor(slot="helmet")},
            13: {"Description": _Desc(name="Dagger"),
                 "Weapon": _Weapon()},
        })
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())
        names = [i["name"] for i in stats["items"]]
        assert "Chain Mail" not in names
        assert "Shield" not in names
        assert "Helmet" not in names
        assert "Dagger" in names

    def test_unequipped_ring_stays_in_items(self):
        pc = _player_comps()
        pc["Inventory"].slots = [20]
        world = _mock_world({
            1: pc,
            20: {"Description": _Desc(name="Ring of Mending"),
                 "Ring": _Ring()},
        })
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())
        names = [i["name"] for i in stats["items"]]
        assert "Ring of Mending" in names

    def test_slots_used_still_counts_equipped(self):
        """Total slots must include equipped items (Knave rules)."""
        pc = _player_comps()
        pc["Equipment"].weapon = 10
        pc["Inventory"].slots = [10, 11]
        world = _mock_world({
            1: pc,
            10: {"Description": _Desc(name="Greatsword"),
                 "Weapon": _Weapon(slots=2)},
            11: {"Description": _Desc(name="Potion"),
                 "Consumable": _Consumable()},
        })
        wc = WebClient(lang="en")
        stats = _merged_stats(wc, world, 1, 0, _mock_level())
        # 2 (greatsword) + 1 (potion) = 3
        assert stats["slots_used"] == 3


class TestDisconnectHandling:
    """get_input returns disconnect signal on disconnect sentinel."""

    def test_disconnect_sentinel_dict(self):
        wc = WebClient(lang="en")
        wc._in_queue.put({"type": "disconnect"})
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(wc.get_input())
        finally:
            loop.close()
        assert result == ("disconnect", None)

    def test_disconnect_sentinel_json_string(self):
        wc = WebClient(lang="en")
        wc._in_queue.put(json.dumps({"type": "disconnect"}))
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(wc.get_input())
        finally:
            loop.close()
        assert result == ("disconnect", None)

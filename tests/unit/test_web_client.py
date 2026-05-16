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
    wc = WebClient(style="classic", lang="ca")
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
        assert wc.style == "classic"
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

    def test_repeated_messages_are_throttled(self, client):
        # 6 identical messages collapse to 2 visible: raw + (x5).
        for _ in range(6):
            client.add_message("you see a villager")
        assert client.messages == [
            "you see a villager",
            "you see a villager (x5)",
        ]
        # WebSocket emissions match the in-memory buffer.
        sent_texts = [m["text"] for m in _drain_queue(client)
                      if m.get("type") == "message"]
        assert sent_texts == [
            "you see a villager",
            "you see a villager (x5)",
        ]

    def test_throttle_flushes_rollup_on_break(self, client):
        for _ in range(8):
            client.add_message("you see a villager")
        client.add_message("the door creaks open")
        assert client.messages == [
            "you see a villager",
            "you see a villager (x5)",
            "you see a villager (x2)",
            "the door creaks open",
        ]


class TestWebClientRender:
    def test_render_queues_state_and_stats(self, client):
        """With no game reference attached, render() falls back to
        the ``state_dungeon`` frame (the safest combat-capable
        default). Production paths always attach ``_hex_game``
        first; the view-dispatch tests below cover that case."""
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
        assert "state_dungeon" in types
        assert "stats" in types
        state = next(m for m in msgs if m["type"] == "state_dungeon")
        assert state["turn"] == 5
        # First render sends stats_init (static) + stats (dynamic)
        assert "stats_init" in types
        stats_init = next(m for m in msgs if m["type"] == "stats_init")
        assert "char_name" in stats_init
        stats = next(m for m in msgs if m["type"] == "stats")
        assert "hp" in stats


class TestWebClientStateDispatch:
    """``render()`` picks the state message type via the game's
    :func:`Game.current_view` classifier. See ``design/views.md``
    for the five-view model and the wire protocol."""

    def _mock_world_and_level(self):
        world = MagicMock()
        world._entities = []
        world.get_component = MagicMock(return_value=None)
        level = MagicMock()
        level.height = 0
        level.width = 0
        level.depth = 1
        level.name = "Test"
        return world, level

    def _stub_game(self, view: str):
        """Return an object with a ``.current_view()`` method that
        pins the classifier result. WebClient.render only reads
        that method on its ``_hex_game`` attribute."""
        stub = MagicMock()
        stub.current_view = MagicMock(return_value=view)
        return stub

    @pytest.mark.parametrize(
        "view, expected_type",
        [
            ("site", "state_site"),
            ("structure", "state_structure"),
            ("dungeon", "state_dungeon"),
        ],
    )
    def test_render_emits_view_specific_type(
        self, client, view, expected_type,
    ):
        world, level = self._mock_world_and_level()
        client._hex_game = self._stub_game(view)
        client.render(world, level, player_id=1, turn=5)
        msgs = _drain_queue(client)
        types = [m["type"] for m in msgs]
        assert expected_type in types
        # And no generic "state" frame leaks through -- the
        # client-side dispatch only listens on the split names.
        assert "state" not in types


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

    def test_selection_menu_roundtrips_string_ids(self, client):
        """Hex-mode dialogs (Fight/Flee/Talk, permadeath/cheat)
        carry string IDs instead of int entity IDs. The menu
        protocol must preserve them through the WebSocket round
        trip so the Python side can map them back to enums."""
        client._in_queue.put('{"type":"menu_select","choice":"fight"}')
        result = client.show_selection_menu(
            "You run into foes",
            [("fight", "Fight"), ("flee", "Flee"), ("talk", "Talk")],
        )
        sent = _last_sent(client)
        assert sent["type"] == "menu"
        option_ids = [opt["id"] for opt in sent["options"]]
        assert option_ids == ["fight", "flee", "talk"]
        assert result == "fight"


class TestWebClientNarrativeLog:
    """WebClient must expose narrative_log for typed mode."""

    def test_has_narrative_log(self, client):
        assert hasattr(client, "narrative_log")

    def test_add_mechanical_does_not_raise(self, client):
        client.narrative_log.add_mechanical("> attack goblin")

    def test_add_mechanical_typed_mode(self):
        wc = WebClient(style="typed")
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
        wc = WebClient(style="typed")
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


class TestUILabels:
    """_ui_labels includes translated labels for toolbar, inventory, etc."""

    def test_action_labels_present(self):
        wc = WebClient(lang="en")
        labels = wc._ui_labels()
        for key in ("use", "quaff", "zap", "equip", "unequip",
                     "drop", "throw"):
            assert key in labels, f"missing label for '{key}'"

    def test_action_labels_catalan(self):
        i18n_init("ca")
        wc = WebClient(lang="ca")
        labels = wc._ui_labels()
        # Catalan labels should not be the English fallback keys
        assert labels["drop"] != "ui.action_drop"
        assert labels["use"] != "ui.action_use"

    def test_ui_chrome_labels_present(self):
        wc = WebClient(lang="en")
        labels = wc._ui_labels()
        chrome_keys = [
            "inventory_title", "equipment_section",
            "backpack_section", "inventory_empty", "close_button",
            "help_title", "help_loading", "help_close_hint",
            "help_unavailable", "help_button",
            "victory_title", "death_title", "death_cause",
            "end_footer", "game_continue",
            "loading_generate", "loading_resume",
            "farlook_hint", "autolook_on", "autolook_off",
            "help_command",
            "restart_confirm", "restart_yes", "restart_cancel",
            "mode_classic_tag", "mode_typed_tag",
            "input_placeholder", "empty",
            "stat_str", "stat_dex", "stat_con",
            "stat_int", "stat_wis", "stat_cha",
            "lv", "xp",
        ]
        for key in chrome_keys:
            assert key in labels, f"missing UI label '{key}'"
            assert labels[key], f"empty UI label '{key}'"


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


class TestWebClientFloorMessage:
    """Floor message must include theme and feeling for future use."""

    def _send_floor(self, theme="dungeon", feeling="normal"):
        from nhc.dungeon.model import Level, LevelMetadata, Terrain, Tile
        wc = WebClient(lang="en")
        level = Level.create_empty("t", "T", depth=1, width=5, height=5)
        level.metadata = LevelMetadata(theme=theme, feeling=feeling)
        for y in range(1, 4):
            for x in range(1, 4):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        world = MagicMock()
        world._entities = []
        world.get_component = MagicMock(return_value=None)
        wc.send_floor_change(level, world, player_id=1, turn=1)
        msgs = _drain_queue(wc)
        return next(m for m in msgs if m["type"] == "floor")

    def test_floor_message_includes_theme(self):
        msg = self._send_floor(theme="cave")
        assert msg["theme"] == "cave"

    def test_floor_message_includes_feeling(self):
        msg = self._send_floor(feeling="flooded")
        assert msg["feeling"] == "flooded"


class TestWallMaskComputation:
    """_wall_mask and _is_walkable mirror svg.py's wall rule."""

    def _rect_room(self):
        from nhc.dungeon.model import Level, Terrain, Tile
        # 5x5 grid, FLOOR rect at (1,1)–(3,3), WALL ring around it,
        # VOID corners untouched (default terrain is WALL).
        level = Level.create_empty("t", "T", depth=1, width=5, height=5)
        for y in range(5):
            for x in range(5):
                level.tiles[y][x] = Tile(terrain=Terrain.WALL)
        for y in range(1, 4):
            for x in range(1, 4):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        return level

    def test_interior_floor_has_no_wall_edges(self):
        from nhc.rendering.web_client import _wall_mask
        level = self._rect_room()
        # Center tile (2,2): all 4 neighbours are FLOOR → mask 0.
        assert _wall_mask(level, 2, 2) == 0

    def test_corner_floor_has_two_wall_edges(self):
        from nhc.rendering.web_client import _wall_mask
        level = self._rect_room()
        # NW corner floor (1,1): walls north and west.
        mask = _wall_mask(level, 1, 1)
        assert mask & 1, "north bit should be set"
        assert mask & 8, "west bit should be set"
        assert not (mask & 2), "east bit should be clear"
        assert not (mask & 4), "south bit should be clear"

    def test_edge_floor_has_one_wall_edge(self):
        from nhc.rendering.web_client import _wall_mask
        level = self._rect_room()
        # North edge floor (2,1): only north is a wall.
        assert _wall_mask(level, 2, 1) == 1

    def test_closed_door_is_walkable(self):
        from nhc.dungeon.model import Tile, Terrain
        from nhc.rendering.web_client import _is_walkable
        level = self._rect_room()
        level.tiles[1][2] = Tile(
            terrain=Terrain.FLOOR, feature="door_closed")
        assert _is_walkable(level, 2, 1) is True

    def test_floor_tile_next_to_door_has_door_side_wall_bit(self):
        """A visible door replaces a wall segment, so the adjacent
        floor tile must still report a wall on that side. This
        keeps the clearHatch polygon continuous across the door
        even when the door tile itself is gated out of the
        polygon (approach-side not yet visible)."""
        from nhc.dungeon.model import Tile, Terrain
        from nhc.rendering.web_client import _wall_mask
        level = self._rect_room()
        # Place a closed door on the north edge of the room at
        # (2, 1). The FLOOR interior tile (2, 2) sits directly
        # south of it.
        level.tiles[1][2] = Tile(
            terrain=Terrain.FLOOR,
            feature="door_closed",
            door_side="north",
        )
        # Without the door the bare interior tile has mask 0;
        # with a door neighbour to the north, the N bit must be
        # set so the polygon edge at that boundary is traced as
        # a wall and offset outward.
        mask = _wall_mask(level, 2, 2)
        assert mask & 1, "north bit should be set (door neighbour)"
        assert not (mask & 2)
        assert not (mask & 4)
        assert not (mask & 8)

    def test_secret_door_neighbour_has_wall_bit(self):
        """Secret doors are door tiles, so the same door-aware
        rule as visible doors applies: the neighbour sees a
        wall edge on the door side."""
        from nhc.dungeon.model import Tile, Terrain
        from nhc.rendering.web_client import _wall_mask
        level = self._rect_room()
        level.tiles[1][2] = Tile(
            terrain=Terrain.FLOOR,
            feature="door_secret",
            door_side="north",
        )
        mask = _wall_mask(level, 2, 2)
        assert mask & 1, "north bit set for secret-door neighbour"

    def test_secret_door_is_not_walkable(self):
        from nhc.dungeon.model import Tile, Terrain
        from nhc.rendering.web_client import _is_walkable
        level = self._rect_room()
        level.tiles[1][2] = Tile(
            terrain=Terrain.FLOOR, feature="door_secret")
        assert _is_walkable(level, 2, 1) is False

    def test_corridor_has_parallel_wall_edges(self):
        from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
        from nhc.rendering.web_client import _wall_mask
        # 1-tile-wide horizontal corridor: FLOOR at row 2,
        # WALL on rows 1 and 3, VOID (default WALL) elsewhere.
        level = Level.create_empty("t", "T", depth=1, width=5, height=5)
        for y in range(5):
            for x in range(5):
                level.tiles[y][x] = Tile(terrain=Terrain.WALL)
        for x in range(1, 4):
            level.tiles[2][x] = Tile(
                terrain=Terrain.FLOOR,
                surface_type=SurfaceType.CORRIDOR,
            )
        # Middle of corridor (2,2): walls N and S, no E/W.
        mask = _wall_mask(level, 2, 2)
        assert mask & 1, "north bit set"
        assert mask & 4, "south bit set"
        assert not (mask & 2)
        assert not (mask & 8)
        # End of corridor (1,2): walls N, S, and W.
        mask = _wall_mask(level, 1, 2)
        assert mask & 1 and mask & 4 and mask & 8

    def test_gather_walk_includes_masks(self):
        from nhc.rendering.web_client import WebClient
        wc = WebClient(lang="en")
        level = self._rect_room()
        # Mark the whole floor rect as visible.
        for y in range(1, 4):
            for x in range(1, 4):
                level.tiles[y][x].visible = True
        entries = wc._gather_walk(level)
        assert len(entries) == 9
        for entry in entries:
            assert len(entry) == 3
            x, y, mask = entry
            assert 0 <= mask <= 15
        # Center should have mask 0.
        center = next(e for e in entries if e[0] == 2 and e[1] == 2)
        assert center[2] == 0


class TestDoorWallMask:
    """Door tiles get walls on the two edges orthogonal to
    their door_side, regardless of neighbour terrain, and are
    always included in the polygon when visible."""

    def _wall_column_with_secret_door(self):
        from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
        # 5x5 grid. Vertical wall column at x=2, rooms on each
        # side. A secret door sits at (2, 2) in the wall column.
        level = Level.create_empty("t", "T", depth=1, width=5, height=5)
        for y in range(5):
            for x in range(5):
                level.tiles[y][x] = Tile(terrain=Terrain.WALL)
        # West corridor at x=1
        for y in range(1, 4):
            level.tiles[y][1] = Tile(
                terrain=Terrain.FLOOR,
                surface_type=SurfaceType.CORRIDOR,
            )
        # East room at x=3
        for y in range(1, 4):
            level.tiles[y][3] = Tile(terrain=Terrain.FLOOR)
        # Secret door at (2, 2) on the east edge of the tile
        level.tiles[2][2] = Tile(
            terrain=Terrain.FLOOR,
            feature="door_secret",
            door_side="east",
        )
        return level

    def test_east_door_walls_north_east_south(self):
        from nhc.rendering.web_client import _wall_mask
        level = self._wall_column_with_secret_door()
        mask = _wall_mask(level, 2, 2)
        # door_side=east → walls on N (orthogonal), E (door
        # edge), S (orthogonal). W is the player's approach
        # side and is left clear.
        assert mask & 1, "north wall bit should be set"
        assert mask & 2, "east wall bit should be set"
        assert mask & 4, "south wall bit should be set"
        assert not (mask & 8), "west bit must be clear (approach side)"

    def test_open_door_uses_same_override(self):
        from nhc.dungeon.model import Tile, Terrain
        from nhc.rendering.web_client import _wall_mask
        level = self._wall_column_with_secret_door()
        level.tiles[2][2] = Tile(
            terrain=Terrain.FLOOR,
            feature="door_open",
            door_side="east",
        )
        assert _wall_mask(level, 2, 2) == 1 | 2 | 4

    def test_horizontal_door_walls_north_east_west(self):
        from nhc.dungeon.model import Level, Terrain, Tile
        from nhc.rendering.web_client import _wall_mask
        level = Level.create_empty("t", "T", depth=1, width=5, height=5)
        for y in range(5):
            for x in range(5):
                level.tiles[y][x] = Tile(terrain=Terrain.WALL)
        # Horizontal wall row at y=2 with a closed door at (2, 2)
        level.tiles[2][2] = Tile(
            terrain=Terrain.FLOOR,
            feature="door_closed",
            door_side="north",
        )
        mask = _wall_mask(level, 2, 2)
        # door_side=north → walls on W (orthogonal), N (door
        # edge), E (orthogonal). S (approach) is clear.
        assert mask & 1, "north wall bit set (door edge)"
        assert mask & 2, "east wall bit set (orthogonal)"
        assert mask & 8, "west wall bit set (orthogonal)"
        assert not (mask & 4), "south bit clear (approach side)"

    def test_door_included_when_approach_side_visible(self):
        """Corridor side visible → door joins the polygon with
        the three-bit wall mask."""
        from nhc.rendering.web_client import WebClient
        wc = WebClient(lang="en")
        level = self._wall_column_with_secret_door()
        # door_side=east → approach side is west (corridor)
        level.tiles[2][2].visible = True
        level.tiles[2][1].visible = True  # west neighbour = corridor
        entries = wc._gather_walk(level)
        coords = {(e[0], e[1]): e[2] for e in entries}
        assert (2, 2) in coords, (
            "visible door with visible approach side must "
            "appear in _gather_walk"
        )
        assert coords[(2, 2)] == 1 | 2 | 4

    def test_door_excluded_when_only_far_side_visible(self):
        """Room side visible but corridor not → door stays out
        of the polygon. The room's own W-wall halo will render
        the door visual without leaking into the corridor."""
        from nhc.rendering.web_client import WebClient
        wc = WebClient(lang="en")
        level = self._wall_column_with_secret_door()
        # door_side=east → approach is west; make the east
        # (room) side visible but leave the west side hidden.
        level.tiles[2][2].visible = True
        level.tiles[2][3].visible = True  # east neighbour = room
        level.tiles[2][1].visible = False
        entries = wc._gather_walk(level)
        coords = {(e[0], e[1]) for e in entries}
        assert (2, 2) not in coords, (
            "visible door with no approach-side view must NOT "
            "appear in _gather_walk"
        )

    def test_explored_door_polygon_gate(self):
        """Same gate applies to the bulk explored reveal."""
        from nhc.rendering.web_client import WebClient
        wc = WebClient(lang="en")
        level = self._wall_column_with_secret_door()
        level.tiles[2][2].explored = True
        # Approach side not explored → door entry has mask=-1
        # so it only contributes to drawFog's memory set.
        entries = wc._gather_explored(level)
        entry = next(e for e in entries if e[0] == 2 and e[1] == 2)
        assert entry[2] == -1
        # Now mark the approach side explored → door joins the
        # polygon with the three-bit mask.
        level.tiles[2][1].explored = True
        entries = wc._gather_explored(level)
        entry = next(e for e in entries if e[0] == 2 and e[1] == 2)
        assert entry[2] == 1 | 2 | 4


class TestPolygonRectExpansion:
    """Circle, octagon, and circular/octagonal halves of hybrid
    rooms should join the clearHatch polygon as their full
    bounding rect (or half-rect) — otherwise the walls drawn
    beyond the tile footprint have no polygon coverage and the
    hatching bleeds through the wall visual."""

    def _circle_level(self):
        """5x5 level with a single 5x5 circle room. The diameter
        is 5, so 13 tiles form the circle interior and 12 corner
        tiles remain WALL under the circle's bounding rect."""
        from nhc.dungeon.model import (
            CircleShape, Level, Rect, Room, Terrain, Tile,
        )
        level = Level.create_empty("t", "T", depth=1,
                                   width=7, height=7)
        for y in range(7):
            for x in range(7):
                level.tiles[y][x] = Tile(terrain=Terrain.WALL)
        rect = Rect(1, 1, 5, 5)
        shape = CircleShape()
        room = Room(id="r1", rect=rect, shape=shape)
        level.rooms.append(room)
        for (x, y) in shape.floor_tiles(rect):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
            level.tiles[y][x].visible = True
            level.tiles[y][x].explored = True
        return level, rect

    def test_circle_room_expands_to_bounding_rect(self):
        from nhc.rendering.web_client import WebClient
        wc = WebClient(lang="en")
        level, rect = self._circle_level()
        entries = wc._gather_walk(level)
        coords = {(e[0], e[1]) for e in entries}
        # Every tile in the 5x5 bounding rect must be present,
        # including the four corner WALL tiles (1,1), (5,1),
        # (1,5), (5,5) which lie outside the circle.
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                assert (x, y) in coords, (
                    f"({x},{y}) missing from polygon; circle room "
                    f"must expand to its bounding rect"
                )
        # The four corners must have mask bits set for their
        # outer edges (NW corner = N|W, etc.) so the polygon
        # traces a rectangular perimeter.
        mask_of = {(e[0], e[1]): e[2] for e in entries}
        assert mask_of[(1, 1)] == 1 | 8  # N | W
        assert mask_of[(5, 1)] == 1 | 2  # N | E
        assert mask_of[(1, 5)] == 4 | 8  # S | W
        assert mask_of[(5, 5)] == 2 | 4  # S | E

    def test_octagon_room_expands_to_bounding_rect(self):
        """Octagonal rooms have diagonal walls that cut off the
        corners. The polygon must still cover the full bounding
        rect so the diagonal wall stroke erases the hatching."""
        from nhc.dungeon.model import (
            Level, OctagonShape, Rect, Room, Terrain, Tile,
        )
        from nhc.rendering.web_client import WebClient
        level = Level.create_empty("t", "T", depth=1,
                                   width=9, height=9)
        for y in range(9):
            for x in range(9):
                level.tiles[y][x] = Tile(terrain=Terrain.WALL)
        rect = Rect(1, 1, 7, 7)
        shape = OctagonShape()
        room = Room(id="r1", rect=rect, shape=shape)
        level.rooms.append(room)
        for (x, y) in shape.floor_tiles(rect):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
            level.tiles[y][x].visible = True
        wc = WebClient(lang="en")
        entries = wc._gather_walk(level)
        coords = {(e[0], e[1]) for e in entries}
        # Corner tiles clipped by the octagon (e.g. (1,1)) must
        # still be in the polygon.
        assert (1, 1) in coords
        assert (7, 1) in coords
        assert (1, 7) in coords
        assert (7, 7) in coords

    def test_hybrid_circle_rect_expands_circle_half_only(self):
        """Hybrid(circle, rect) must expand the circle half to
        its half-rect while the rect half already covers its
        own half naturally."""
        from nhc.dungeon.model import (
            CircleShape, HybridShape, Level, Rect, RectShape,
            Room, Terrain, Tile,
        )
        from nhc.rendering.web_client import WebClient
        level = Level.create_empty("t", "T", depth=1,
                                   width=12, height=8)
        for y in range(8):
            for x in range(12):
                level.tiles[y][x] = Tile(terrain=Terrain.WALL)
        # Hybrid rect = (1,1,10,5). Vertical split → circle on
        # the left half (1..5, height 5), rect on the right half
        # (6..10, height 5).
        rect = Rect(1, 1, 10, 5)
        shape = HybridShape(
            left=CircleShape(), right=RectShape(),
            split="vertical",
        )
        room = Room(id="r1", rect=rect, shape=shape)
        level.rooms.append(room)
        for (x, y) in shape.floor_tiles(rect):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
            level.tiles[y][x].visible = True
        wc = WebClient(lang="en")
        entries = wc._gather_walk(level)
        coords = {(e[0], e[1]) for e in entries}
        # Circle-half corners (inside the left half-rect) must
        # be present even though they are WALL terrain.
        assert (1, 1) in coords
        assert (1, 5) in coords

    def test_rect_room_unchanged_by_expansion(self):
        """Pure rect rooms have no corners to fill — the polygon
        should match the room's floor tiles as before."""
        from nhc.dungeon.model import (
            Level, Rect, RectShape, Room, Terrain, Tile,
        )
        from nhc.rendering.web_client import WebClient
        level = Level.create_empty("t", "T", depth=1,
                                   width=7, height=7)
        for y in range(7):
            for x in range(7):
                level.tiles[y][x] = Tile(terrain=Terrain.WALL)
        rect = Rect(2, 2, 3, 3)
        room = Room(id="r1", rect=rect, shape=RectShape())
        level.rooms.append(room)
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
                level.tiles[y][x].visible = True
        wc = WebClient(lang="en")
        entries = wc._gather_walk(level)
        coords = {(e[0], e[1]) for e in entries}
        assert coords == {
            (x, y)
            for y in range(rect.y, rect.y2)
            for x in range(rect.x, rect.x2)
        }

    def test_circle_expansion_gated_by_visibility(self):
        """Expansion tiles only join the polygon when at least
        one floor tile of the sub-shape is visible."""
        from nhc.rendering.web_client import WebClient
        level, rect = self._circle_level()
        # Reset visibility: nothing visible.
        for y in range(level.height):
            for x in range(level.width):
                level.tiles[y][x].visible = False
        wc = WebClient(lang="en")
        entries = wc._gather_walk(level)
        coords = {(e[0], e[1]) for e in entries}
        assert (1, 1) not in coords, (
            "corner must not be in polygon when the room has "
            "no visible floor tile"
        )

    def _pill_level(self):
        """A 9x5 horizontal pill room. d=5, r=2. The four bounding
        rect corners (1,1), (9,1), (1,5), (9,5) are clipped by the
        semicircle caps and remain WALL terrain."""
        from nhc.dungeon.model import (
            Level, PillShape, Rect, Room, Terrain, Tile,
        )
        level = Level.create_empty("t", "T", depth=1,
                                   width=11, height=7)
        for y in range(7):
            for x in range(11):
                level.tiles[y][x] = Tile(terrain=Terrain.WALL)
        rect = Rect(1, 1, 9, 5)
        shape = PillShape()
        room = Room(id="r1", rect=rect, shape=shape)
        level.rooms.append(room)
        for (x, y) in shape.floor_tiles(rect):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
            level.tiles[y][x].visible = True
            level.tiles[y][x].explored = True
        return level, rect

    def test_pill_room_expands_to_bounding_rect(self):
        """Pill rooms clip the four bounding-rect corners with
        the semicircle caps; the clearHatch polygon must still
        cover those corners so the curved wall stroke erases
        the hatching behind it."""
        from nhc.rendering.web_client import WebClient
        wc = WebClient(lang="en")
        level, rect = self._pill_level()
        entries = wc._gather_walk(level)
        coords = {(e[0], e[1]) for e in entries}
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                assert (x, y) in coords, (
                    f"({x},{y}) missing from polygon; pill room "
                    f"must expand to its bounding rect"
                )
        # The four clipped corners must have masks that trace
        # the rectangular perimeter (N|W, N|E, S|W, S|E).
        mask_of = {(e[0], e[1]): e[2] for e in entries}
        assert mask_of[(1, 1)] == 1 | 8   # N | W
        assert mask_of[(9, 1)] == 1 | 2   # N | E
        assert mask_of[(1, 5)] == 4 | 8   # S | W
        assert mask_of[(9, 5)] == 2 | 4   # S | E

    def test_pill_expansion_gated_by_visibility(self):
        """Pill expansion cells only appear once the room has
        at least one visible floor tile."""
        from nhc.rendering.web_client import WebClient
        level, _ = self._pill_level()
        for y in range(level.height):
            for x in range(level.width):
                level.tiles[y][x].visible = False
        wc = WebClient(lang="en")
        entries = wc._gather_walk(level)
        coords = {(e[0], e[1]) for e in entries}
        assert (1, 1) not in coords

    def _temple_level(self):
        """A 9x9 temple room (south-flat). The cross shape leaves
        all four bounding-rect corners as WALL — the polygon must
        still cover them so the curved cap and diagonal walls
        erase the hatching behind the wall stroke."""
        from nhc.dungeon.model import (
            Level, Rect, Room, TempleShape, Terrain, Tile,
        )
        level = Level.create_empty("t", "T", depth=1,
                                   width=11, height=11)
        for y in range(11):
            for x in range(11):
                level.tiles[y][x] = Tile(terrain=Terrain.WALL)
        rect = Rect(1, 1, 9, 9)
        shape = TempleShape(flat_side="south")
        room = Room(id="r1", rect=rect, shape=shape)
        level.rooms.append(room)
        for (x, y) in shape.floor_tiles(rect):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
            level.tiles[y][x].visible = True
            level.tiles[y][x].explored = True
        return level, rect

    def test_temple_room_expands_to_bounding_rect(self):
        """Temple rooms clip the four bounding-rect corners via
        the cross body; clearHatch must still cover the full
        bounding rect."""
        from nhc.rendering.web_client import WebClient
        wc = WebClient(lang="en")
        level, rect = self._temple_level()
        entries = wc._gather_walk(level)
        coords = {(e[0], e[1]) for e in entries}
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                assert (x, y) in coords, (
                    f"({x},{y}) missing from polygon; temple room "
                    f"must expand to its bounding rect"
                )
        mask_of = {(e[0], e[1]): e[2] for e in entries}
        assert mask_of[(1, 1)] == 1 | 8   # N | W
        assert mask_of[(9, 1)] == 1 | 2   # N | E
        assert mask_of[(1, 9)] == 4 | 8   # S | W
        assert mask_of[(9, 9)] == 2 | 4   # S | E

    def test_temple_expansion_gated_by_visibility(self):
        from nhc.rendering.web_client import WebClient
        level, _ = self._temple_level()
        for y in range(level.height):
            for x in range(level.width):
                level.tiles[y][x].visible = False
        wc = WebClient(lang="en")
        entries = wc._gather_walk(level)
        coords = {(e[0], e[1]) for e in entries}
        assert (1, 1) not in coords

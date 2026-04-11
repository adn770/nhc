"""Tests for the GetHenchmanSheetsTool MCP debug tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nhc.core.ecs import World
from nhc.core.save import _serialize_entities
from nhc.debug_tools.tools.game_state import (
    GetHenchmanSheetsTool,
    build_henchman_sheets,
)
from nhc.entities.components import (
    AI,
    Armor,
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


@pytest.fixture()
def tmp_exports(tmp_path, monkeypatch):
    """Create a tmp exports dir and point the tool at it."""
    exp_dir = tmp_path / "debug" / "exports"
    exp_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return exp_dir


def _write_game_state(exports: Path, ecs: dict) -> None:
    data = {
        "timestamp": "2026-04-11T10:00:00",
        "turn": 5,
        "player_id": 1,
        "ecs": ecs,
    }
    (exports / "game_state_20260411_100000.json").write_text(
        json.dumps(data)
    )


class TestGetHenchmanSheetsTool:
    @pytest.mark.asyncio
    async def test_no_export_returns_error(self, tmp_exports):
        tool = GetHenchmanSheetsTool()
        result = await tool.execute()
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_henchmen_returns_empty_list(self, tmp_exports):
        _write_game_state(tmp_exports, ecs={
            "1": {  # player
                "Player": {
                    "xp": 0, "level": 1,
                    "xp_to_next": 1000, "gold": 0,
                },
                "Stats": {
                    "strength": 1, "dexterity": 2,
                    "constitution": 1, "intelligence": 0,
                    "wisdom": 0, "charisma": 1,
                },
                "Health": {"current": 8, "maximum": 8},
                "Description": {
                    "name": "Hero", "short": "the hero",
                    "long": "", "gender": "m", "plural": "",
                },
            },
        })
        tool = GetHenchmanSheetsTool()
        result = await tool.execute()
        assert result == {"henchmen": [], "count": 0}

    @pytest.mark.asyncio
    async def test_full_henchman_sheet(self, tmp_exports):
        ecs = {
            "1": {  # player (ignored)
                "Player": {
                    "xp": 0, "level": 1,
                    "xp_to_next": 1000, "gold": 0,
                },
            },
            "42": {  # henchman
                "Henchman": {
                    "owner": 1, "level": 3,
                    "xp": 2000, "xp_to_next": 3000,
                    "hired": True, "called_for_help": False,
                },
                "Stats": {
                    "strength": 2, "dexterity": 1,
                    "constitution": 3, "intelligence": 0,
                    "wisdom": 1, "charisma": 2,
                },
                "Health": {"current": 12, "maximum": 18},
                "Description": {
                    "name": "Bob the Brave",
                    "short": "Bob the Brave",
                    "long": "", "gender": "m", "plural": "",
                },
                "Equipment": {
                    "weapon": 50, "armor": 51, "shield": None,
                    "helmet": None, "ring_left": None,
                    "ring_right": None,
                },
                "Inventory": {"slots": [52, 53], "max_slots": 13},
            },
            "50": {  # equipped weapon
                "Weapon": {
                    "damage": "1d8", "type": "melee",
                    "slots": 1, "magic_bonus": 1,
                },
                "Description": {
                    "name": "long sword", "short": "a long sword",
                    "long": "", "gender": "", "plural": "",
                },
                "RegistryId": {"item_id": "long_sword"},
            },
            "51": {  # equipped armor
                "Armor": {
                    "slot": "body", "defense": 13,
                    "slots": 2, "magic_bonus": 0,
                },
                "Description": {
                    "name": "chain mail",
                    "short": "a chain mail hauberk",
                    "long": "", "gender": "", "plural": "",
                },
                "RegistryId": {"item_id": "chain_mail"},
            },
            "52": {  # inventory: potion
                "Consumable": {
                    "effect": "heal", "dice": "2d6", "slots": 1,
                },
                "Description": {
                    "name": "healing potion",
                    "short": "a healing potion",
                    "long": "", "gender": "", "plural": "",
                },
            },
            "53": {  # inventory: backup dagger
                "Weapon": {
                    "damage": "1d4", "type": "melee",
                    "slots": 1, "magic_bonus": 0,
                },
                "Description": {
                    "name": "dagger", "short": "a dagger",
                    "long": "", "gender": "", "plural": "",
                },
            },
        }
        _write_game_state(tmp_exports, ecs=ecs)

        tool = GetHenchmanSheetsTool()
        result = await tool.execute()

        assert result["count"] == 1
        sheet = result["henchmen"][0]
        assert sheet["id"] == 42
        assert sheet["name"] == "Bob the Brave"
        assert sheet["level"] == 3
        assert sheet["xp"] == 2000
        assert sheet["xp_to_next"] == 3000
        assert sheet["hired"] is True
        assert sheet["hp"] == 12
        assert sheet["max_hp"] == 18
        assert sheet["stats"] == {
            "strength": 2, "dexterity": 1,
            "constitution": 3, "intelligence": 0,
            "wisdom": 1, "charisma": 2,
        }

        weapon = sheet["equipment"]["weapon"]
        assert weapon["id"] == 50
        assert weapon["name"] == "long sword"
        assert weapon["damage"] == "1d8"
        assert weapon["magic_bonus"] == 1

        armor = sheet["equipment"]["armor"]
        assert armor["id"] == 51
        assert armor["name"] == "chain mail"
        assert armor["defense"] == 13
        assert armor["slot"] == "body"

        # Empty slots are reported as None
        assert sheet["equipment"]["shield"] is None
        assert sheet["equipment"]["helmet"] is None
        assert sheet["equipment"]["ring_left"] is None
        assert sheet["equipment"]["ring_right"] is None

        inv = sheet["inventory"]
        assert len(inv) == 2
        names = {item["name"] for item in inv}
        assert names == {"healing potion", "dagger"}
        # Type is identified for items
        types = {item["type"] for item in inv}
        assert types == {"consumable", "weapon"}

    @pytest.mark.asyncio
    async def test_multiple_henchmen(self, tmp_exports):
        def _henchman(eid: int, name: str, level: int) -> dict:
            return {
                "Henchman": {
                    "owner": 1, "level": level,
                    "xp": 0, "xp_to_next": 1000,
                    "hired": True, "called_for_help": False,
                },
                "Stats": {
                    "strength": 0, "dexterity": 0,
                    "constitution": 0, "intelligence": 0,
                    "wisdom": 0, "charisma": 0,
                },
                "Health": {"current": 5, "maximum": 5},
                "Description": {
                    "name": name, "short": name,
                    "long": "", "gender": "", "plural": "",
                },
                "Equipment": {
                    "weapon": None, "armor": None,
                    "shield": None, "helmet": None,
                    "ring_left": None, "ring_right": None,
                },
                "Inventory": {"slots": [], "max_slots": 10},
            }

        ecs = {
            "10": _henchman(10, "Alice", 2),
            "11": _henchman(11, "Bob", 4),
        }
        _write_game_state(tmp_exports, ecs=ecs)

        tool = GetHenchmanSheetsTool()
        result = await tool.execute()
        assert result["count"] == 2
        names = {h["name"] for h in result["henchmen"]}
        assert names == {"Alice", "Bob"}

    @pytest.mark.asyncio
    async def test_filter_by_id(self, tmp_exports):
        ecs = {
            "10": {
                "Henchman": {
                    "owner": 1, "level": 1, "xp": 0,
                    "xp_to_next": 1000, "hired": True,
                    "called_for_help": False,
                },
                "Description": {
                    "name": "Alice", "short": "Alice",
                    "long": "", "gender": "", "plural": "",
                },
            },
            "11": {
                "Henchman": {
                    "owner": 1, "level": 1, "xp": 0,
                    "xp_to_next": 1000, "hired": True,
                    "called_for_help": False,
                },
                "Description": {
                    "name": "Bob", "short": "Bob",
                    "long": "", "gender": "", "plural": "",
                },
            },
        }
        _write_game_state(tmp_exports, ecs=ecs)

        tool = GetHenchmanSheetsTool()
        result = await tool.execute(henchman_id=11)
        assert result["count"] == 1
        assert result["henchmen"][0]["name"] == "Bob"

    @pytest.mark.asyncio
    async def test_filter_by_owner_and_hired(self, tmp_exports):
        ecs = {
            "10": {  # hired by player 1
                "Henchman": {
                    "owner": 1, "level": 1, "xp": 0,
                    "xp_to_next": 1000, "hired": True,
                    "called_for_help": False,
                },
                "Description": {
                    "name": "Hired", "short": "Hired",
                    "long": "", "gender": "", "plural": "",
                },
            },
            "11": {  # not hired
                "Henchman": {
                    "owner": None, "level": 1, "xp": 0,
                    "xp_to_next": 1000, "hired": False,
                    "called_for_help": False,
                },
                "Description": {
                    "name": "Stranger", "short": "Stranger",
                    "long": "", "gender": "", "plural": "",
                },
            },
            "12": {  # hired by player 2
                "Henchman": {
                    "owner": 2, "level": 1, "xp": 0,
                    "xp_to_next": 1000, "hired": True,
                    "called_for_help": False,
                },
                "Description": {
                    "name": "Other", "short": "Other",
                    "long": "", "gender": "", "plural": "",
                },
            },
        }
        result = build_henchman_sheets(
            ecs, hired_only=True, owner_id=1,
        )
        assert result["count"] == 1
        assert result["henchmen"][0]["name"] == "Hired"

    @pytest.mark.asyncio
    async def test_henchman_without_description_falls_back(
        self, tmp_exports,
    ):
        ecs = {
            "20": {
                "Henchman": {
                    "owner": 1, "level": 1, "xp": 0,
                    "xp_to_next": 1000, "hired": False,
                    "called_for_help": False,
                },
            },
        }
        _write_game_state(tmp_exports, ecs=ecs)

        tool = GetHenchmanSheetsTool()
        result = await tool.execute()
        assert result["count"] == 1
        sheet = result["henchmen"][0]
        assert sheet["id"] == 20
        # No Description → name is empty string
        assert sheet["name"] == ""
        # Missing components reported as None / empty
        assert sheet["stats"] is None
        assert sheet["hp"] is None
        assert sheet["equipment"] is None
        assert sheet["inventory"] == []


class TestBuildHenchmanSheetsFromWorld:
    """Sanity-check that the builder works on a serialized live World."""

    def test_live_world_round_trip(self):
        world = World()
        # Player
        pid = world.create_entity({
            "Position": Position(x=1, y=1),
            "Stats": Stats(strength=2, dexterity=2),
            "Health": Health(current=10, maximum=10),
            "Player": Player(gold=100),
            "Description": Description(name="Hero"),
        })

        # Equipped weapon for the henchman
        wid = world.create_entity({
            "Weapon": Weapon(damage="1d8", magic_bonus=1),
            "Description": Description(name="long sword"),
        })
        # Equipped armor
        aid = world.create_entity({
            "Armor": Armor(slot="body", defense=14),
            "Description": Description(name="chain mail"),
        })
        # Carried potion
        potid = world.create_entity({
            "Description": Description(name="healing potion"),
        })

        # Hired henchman owned by the player
        hid = world.create_entity({
            "Position": Position(x=2, y=1),
            "Stats": Stats(
                strength=3, dexterity=1, constitution=2,
                intelligence=0, wisdom=1, charisma=2,
            ),
            "Health": Health(current=12, maximum=18),
            "Inventory": Inventory(slots=[potid], max_slots=12),
            "Equipment": Equipment(weapon=wid, armor=aid),
            "AI": AI(behavior="henchman", faction="human"),
            "Henchman": Henchman(
                owner=pid, level=3, xp=2000,
                xp_to_next=3000, hired=True,
            ),
            "Description": Description(name="Bob the Brave"),
            "Renderable": Renderable(glyph="@", color="cyan"),
        })

        # Unhired adventurer (should be excluded)
        world.create_entity({
            "Henchman": Henchman(
                owner=None, level=1, hired=False,
            ),
            "Description": Description(name="Stranger"),
        })

        ecs = _serialize_entities(world)
        result = build_henchman_sheets(
            ecs, hired_only=True, owner_id=pid,
        )

        assert result["count"] == 1
        sheet = result["henchmen"][0]
        assert sheet["id"] == hid
        assert sheet["name"] == "Bob the Brave"
        assert sheet["level"] == 3
        assert sheet["hp"] == 12
        assert sheet["max_hp"] == 18
        assert sheet["stats"]["strength"] == 3

        weapon = sheet["equipment"]["weapon"]
        assert weapon["name"] == "long sword"
        assert weapon["damage"] == "1d8"
        assert weapon["magic_bonus"] == 1

        armor = sheet["equipment"]["armor"]
        assert armor["name"] == "chain mail"
        assert armor["defense"] == 14

        assert len(sheet["inventory"]) == 1
        assert sheet["inventory"][0]["name"] == "healing potion"

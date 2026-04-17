"""Tests for WorldType and Difficulty enums.

Milestone W1: new enums, derived properties, GameMode compat.
"""

from __future__ import annotations

from nhc.hexcrawl.mode import (
    Difficulty,
    GameMode,
    WorldType,
)


# ---------------------------------------------------------------------------
# WorldType enum
# ---------------------------------------------------------------------------


def test_world_type_values() -> None:
    assert WorldType.HEXCRAWL.value == "hexcrawl"
    assert WorldType.DUNGEON.value == "dungeon"


def test_world_type_from_str() -> None:
    assert WorldType.from_str("hexcrawl") is WorldType.HEXCRAWL
    assert WorldType.from_str("dungeon") is WorldType.DUNGEON


# ---------------------------------------------------------------------------
# Difficulty enum
# ---------------------------------------------------------------------------


def test_difficulty_values() -> None:
    assert Difficulty.EASY.value == "easy"
    assert Difficulty.MEDIUM.value == "medium"
    assert Difficulty.SURVIVAL.value == "survival"


def test_difficulty_from_str() -> None:
    assert Difficulty.from_str("easy") is Difficulty.EASY
    assert Difficulty.from_str("medium") is Difficulty.MEDIUM
    assert Difficulty.from_str("survival") is Difficulty.SURVIVAL


# ---------------------------------------------------------------------------
# Derived properties
# ---------------------------------------------------------------------------


def test_cheat_death_easy_only() -> None:
    assert Difficulty.EASY.allows_cheat_death is True
    assert Difficulty.MEDIUM.allows_cheat_death is False
    assert Difficulty.SURVIVAL.allows_cheat_death is False


def test_double_gold_easy_and_medium() -> None:
    assert Difficulty.EASY.double_gold is True
    assert Difficulty.MEDIUM.double_gold is True
    assert Difficulty.SURVIVAL.double_gold is False


# ---------------------------------------------------------------------------
# GameMode compat — from_world_difficulty
# ---------------------------------------------------------------------------


def test_gamemode_from_world_difficulty_hex_easy() -> None:
    gm = GameMode.from_world_difficulty(
        WorldType.HEXCRAWL, Difficulty.EASY,
    )
    assert gm is GameMode.HEX_EASY


def test_gamemode_from_world_difficulty_hex_medium() -> None:
    gm = GameMode.from_world_difficulty(
        WorldType.HEXCRAWL, Difficulty.MEDIUM,
    )
    assert gm is GameMode.HEX_MEDIUM


def test_gamemode_from_world_difficulty_hex_survival() -> None:
    gm = GameMode.from_world_difficulty(
        WorldType.HEXCRAWL, Difficulty.SURVIVAL,
    )
    assert gm is GameMode.HEX_SURVIVAL


def test_gamemode_from_world_difficulty_dungeon_easy() -> None:
    gm = GameMode.from_world_difficulty(
        WorldType.DUNGEON, Difficulty.EASY,
    )
    assert gm is GameMode.DUNGEON_EASY


def test_gamemode_from_world_difficulty_dungeon_medium() -> None:
    gm = GameMode.from_world_difficulty(
        WorldType.DUNGEON, Difficulty.MEDIUM,
    )
    assert gm is GameMode.DUNGEON_MEDIUM


def test_gamemode_from_world_difficulty_dungeon_survival() -> None:
    gm = GameMode.from_world_difficulty(
        WorldType.DUNGEON, Difficulty.SURVIVAL,
    )
    assert gm is GameMode.DUNGEON_SURVIVAL


# ---------------------------------------------------------------------------
# GameMode derived properties
# ---------------------------------------------------------------------------


def test_gamemode_is_hex() -> None:
    assert GameMode.HEX_EASY.is_hex is True
    assert GameMode.HEX_MEDIUM.is_hex is True
    assert GameMode.HEX_SURVIVAL.is_hex is True
    assert GameMode.DUNGEON_EASY.is_hex is False
    assert GameMode.DUNGEON_MEDIUM.is_hex is False
    assert GameMode.DUNGEON_SURVIVAL.is_hex is False


def test_gamemode_allows_cheat_death() -> None:
    assert GameMode.HEX_EASY.allows_cheat_death is True
    assert GameMode.DUNGEON_EASY.allows_cheat_death is True
    assert GameMode.HEX_MEDIUM.allows_cheat_death is False
    assert GameMode.DUNGEON_MEDIUM.allows_cheat_death is False
    assert GameMode.HEX_SURVIVAL.allows_cheat_death is False
    assert GameMode.DUNGEON_SURVIVAL.allows_cheat_death is False


def test_gamemode_double_gold() -> None:
    assert GameMode.HEX_EASY.double_gold is True
    assert GameMode.DUNGEON_EASY.double_gold is True
    assert GameMode.HEX_MEDIUM.double_gold is True
    assert GameMode.DUNGEON_MEDIUM.double_gold is True
    assert GameMode.HEX_SURVIVAL.double_gold is False
    assert GameMode.DUNGEON_SURVIVAL.double_gold is False


def test_gamemode_world_type() -> None:
    assert GameMode.HEX_EASY.world_type is WorldType.HEXCRAWL
    assert GameMode.DUNGEON_EASY.world_type is WorldType.DUNGEON


def test_gamemode_difficulty() -> None:
    assert GameMode.HEX_EASY.difficulty is Difficulty.EASY
    assert GameMode.DUNGEON_SURVIVAL.difficulty is Difficulty.SURVIVAL


# ---------------------------------------------------------------------------
# Legacy compat
# ---------------------------------------------------------------------------


def test_gamemode_from_str_legacy() -> None:
    """Old 'dungeon' string maps to DUNGEON_MEDIUM (default)."""
    assert GameMode.from_str("dungeon") is GameMode.DUNGEON_MEDIUM


def test_gamemode_from_str_hex_easy_legacy() -> None:
    """Old 'hex-easy' maps to HEX_EASY."""
    assert GameMode.from_str("hex-easy") is GameMode.HEX_EASY


def test_gamemode_from_str_hex_survival_legacy() -> None:
    """Old 'hex-survival' maps to HEX_SURVIVAL."""
    assert GameMode.from_str("hex-survival") is GameMode.HEX_SURVIVAL

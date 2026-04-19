"""GameMode enum and the split ``--world`` / ``--difficulty`` flags.

The two CLI flags are orthogonal: ``--world`` picks the world
shape (hexcrawl overland vs classic dungeon), ``--difficulty``
picks the play difficulty (easy / medium / survival). A third
existing ``--mode`` flag (not tested here) picks the input style
(typed-LLM vs roguelike-keys).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from nhc.hexcrawl.mode import (
    Difficulty, GameMode, WorldType, add_mode_args,
    gamemode_from_args,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# GameMode enum
# ---------------------------------------------------------------------------


def test_gamemode_default_is_dungeon() -> None:
    assert GameMode.default() is GameMode.DUNGEON


def test_gamemode_value_strings() -> None:
    assert GameMode.DUNGEON.value == "dungeon-medium"
    assert GameMode.DUNGEON_MEDIUM.value == "dungeon-medium"
    assert GameMode.HEX_EASY.value == "hex-easy"
    assert GameMode.HEX_SURVIVAL.value == "hex-survival"


def test_gamemode_parses_dungeon() -> None:
    assert GameMode.from_str("dungeon") is GameMode.DUNGEON


def test_gamemode_parses_hex_easy() -> None:
    assert GameMode.from_str("hex-easy") is GameMode.HEX_EASY


def test_gamemode_parses_hex_survival() -> None:
    assert GameMode.from_str("hex-survival") is GameMode.HEX_SURVIVAL


def test_gamemode_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        GameMode.from_str("nonsense")


def test_gamemode_predicates() -> None:
    assert GameMode.DUNGEON.is_dungeon_only
    assert not GameMode.DUNGEON.is_hex
    assert GameMode.HEX_EASY.is_hex
    assert GameMode.HEX_SURVIVAL.is_hex


def test_gamemode_easy_vs_survival_predicates() -> None:
    assert GameMode.HEX_EASY.allows_cheat_death
    assert not GameMode.HEX_SURVIVAL.allows_cheat_death


# ---------------------------------------------------------------------------
# add_mode_args: registers --world and --difficulty as two flags
# ---------------------------------------------------------------------------


def _build_parser(
    default_world: str = "dungeon",
    default_difficulty: str = "medium",
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="test")
    add_mode_args(
        parser,
        default_world=default_world,
        default_difficulty=default_difficulty,
    )
    return parser


def test_add_mode_args_default_is_dungeon_medium() -> None:
    ns = _build_parser().parse_args([])
    assert ns.world == "dungeon"
    assert ns.difficulty == "medium"


def test_add_mode_args_default_override() -> None:
    ns = _build_parser(
        default_world="hexcrawl",
        default_difficulty="survival",
    ).parse_args([])
    assert ns.world == "hexcrawl"
    assert ns.difficulty == "survival"


def test_nhc_web_defaults_to_hex_medium() -> None:
    """The local dev server launches on the hexcrawl overland
    map by default; dungeon-only play requires an explicit
    ``--world dungeon``."""
    from unittest.mock import patch
    from nhc_web import parse_args
    with patch.object(sys, "argv", ["nhc_web.py"]):
        ns = parse_args()
    assert ns.world == "hexcrawl"
    assert ns.difficulty == "medium"


def test_add_mode_args_accepts_world_dungeon() -> None:
    ns = _build_parser().parse_args(["--world", "dungeon"])
    assert ns.world == "dungeon"


def test_add_mode_args_accepts_world_hexcrawl() -> None:
    ns = _build_parser().parse_args(["--world", "hexcrawl"])
    assert ns.world == "hexcrawl"


def test_add_mode_args_accepts_difficulty_easy() -> None:
    ns = _build_parser().parse_args(["--difficulty", "easy"])
    assert ns.difficulty == "easy"


def test_add_mode_args_accepts_difficulty_survival() -> None:
    ns = _build_parser().parse_args(["--difficulty", "survival"])
    assert ns.difficulty == "survival"


def test_add_mode_args_rejects_unknown_world() -> None:
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["--world", "atlantis"])


def test_add_mode_args_rejects_unknown_difficulty() -> None:
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["--difficulty", "nightmare"])


def test_gamemode_from_args_composes_split() -> None:
    ns = _build_parser().parse_args([
        "--world", "hexcrawl", "--difficulty", "easy",
    ])
    assert gamemode_from_args(ns) is GameMode.HEX_EASY


def test_gamemode_from_args_survival_dungeon() -> None:
    ns = _build_parser().parse_args([
        "--world", "dungeon", "--difficulty", "survival",
    ])
    assert gamemode_from_args(ns) is GameMode.DUNGEON_SURVIVAL


# ---------------------------------------------------------------------------
# Integration: --help on the actual nhc.py and nhc_web.py scripts
# ---------------------------------------------------------------------------


def _run_help(script: str) -> str:
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / script), "--help"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_nhc_script_advertises_split_flags() -> None:
    out = _run_help("nhc.py")
    assert "--world" in out
    assert "--difficulty" in out
    assert "hexcrawl" in out
    assert "survival" in out
    # And the existing --mode flag is still there.
    assert "--mode" in out


def test_nhc_web_script_advertises_split_flags() -> None:
    out = _run_help("nhc_web.py")
    assert "--world" in out
    assert "--difficulty" in out
    assert "hexcrawl" in out

"""GameMode enum and the new --world CLI flag.

Plan note: the original M-1.1 spec named the flag --mode, but the
existing nhc.py already exposes --mode {typed,classic} for the
input style (typed-LLM vs roguelike-keys), referenced in the README,
the three help files, and design/typed_gameplay.md. To keep that
surface stable we introduce --world {dungeon,hex-easy,hex-survival}
for the new world-mode axis. The two flags are orthogonal:
--mode controls input, --world controls the overland wrapper.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from nhc.hexcrawl.mode import GameMode, add_world_arg


PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# GameMode enum
# ---------------------------------------------------------------------------


def test_gamemode_default_is_dungeon() -> None:
    assert GameMode.default() is GameMode.DUNGEON


def test_gamemode_value_strings() -> None:
    assert GameMode.DUNGEON.value == "dungeon"
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
# add_world_arg helper (used by both nhc.py and nhc_web.py)
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="test")
    add_world_arg(parser)
    return parser


def test_add_world_arg_default_is_dungeon() -> None:
    ns = _build_parser().parse_args([])
    assert ns.world == "dungeon"


def test_add_world_arg_accepts_dungeon() -> None:
    ns = _build_parser().parse_args(["--world", "dungeon"])
    assert ns.world == "dungeon"


def test_add_world_arg_accepts_hex_easy() -> None:
    ns = _build_parser().parse_args(["--world", "hex-easy"])
    assert ns.world == "hex-easy"


def test_add_world_arg_accepts_hex_survival() -> None:
    ns = _build_parser().parse_args(["--world", "hex-survival"])
    assert ns.world == "hex-survival"


def test_add_world_arg_rejects_unknown() -> None:
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["--world", "atlantis"])


def test_add_world_arg_returns_gamemode_via_helper() -> None:
    ns = _build_parser().parse_args(["--world", "hex-easy"])
    # Convenience helper to translate the parsed string into a
    # GameMode enum value.
    from nhc.hexcrawl.mode import gamemode_from_args
    assert gamemode_from_args(ns) is GameMode.HEX_EASY


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


def test_nhc_script_advertises_world_flag() -> None:
    out = _run_help("nhc.py")
    assert "--world" in out
    assert "hex-easy" in out
    assert "hex-survival" in out
    # And the existing --mode flag is still there.
    assert "--mode" in out


def test_nhc_web_script_advertises_world_flag() -> None:
    out = _run_help("nhc_web.py")
    assert "--world" in out
    assert "hex-easy" in out

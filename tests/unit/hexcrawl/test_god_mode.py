"""God-mode extensions for hex world (M-4.3).

In hex mode, ``set_god_mode(True)`` does two things beyond the
classic item-identify pass:

* disables the encounter roll (``Game.encounters_disabled``
  flag flipped on; downstream callers consult it)
* marks every generated rumor truth=True via the
  ``god_mode_all_rumors_true`` helper

Fog of war is NOT auto-revealed by god mode; use the debug
panel's fog layer toggle to see the full map visually.
"""

from __future__ import annotations

import random

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.rumor_pool import generate_rumors_god_mode
from nhc.i18n import init as i18n_init


class _FakeClient:
    game_mode = "classic"
    lang = "en"
    edge_doors = False
    messages: list[str] = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def _sync(*a, **kw):
            return None

        return _sync


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    i18n_init("en")
    EntityRegistry.discover_all()


def _make_hex_game(tmp_path, god: bool) -> Game:
    g = Game(
        client=_FakeClient(),
        backend=None,
        style="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path,
        seed=42,
        god_mode=god,
    )
    g.initialize()
    return g


# ---------------------------------------------------------------------------
# Reveal-all on god init
# ---------------------------------------------------------------------------


def test_god_mode_does_not_reveal_all_hexes(tmp_path) -> None:
    """God mode should NOT auto-reveal the fog — use the debug
    panel's fog layer toggle instead."""
    g = _make_hex_game(tmp_path, god=True)
    assert g.hex_world is not None
    # Only the hub is revealed at start, not the entire map.
    assert len(g.hex_world.revealed) < len(g.hex_world.cells)


def test_normal_mode_keeps_fog(tmp_path) -> None:
    g = _make_hex_game(tmp_path, god=False)
    assert g.hex_world is not None
    assert len(g.hex_world.revealed) < len(g.hex_world.cells)


def test_set_god_mode_mid_game_does_not_reveal_fog(tmp_path) -> None:
    """Toggling god mode on after init should NOT change fog."""
    g = _make_hex_game(tmp_path, god=False)
    revealed_before = len(g.hex_world.revealed)
    g.set_god_mode(True)
    assert len(g.hex_world.revealed) == revealed_before


# ---------------------------------------------------------------------------
# Encounter rolls disabled
# ---------------------------------------------------------------------------


def test_god_mode_disables_encounter_flag(tmp_path) -> None:
    g = _make_hex_game(tmp_path, god=True)
    assert g.encounters_disabled is True


def test_normal_mode_keeps_encounters_enabled(tmp_path) -> None:
    g = _make_hex_game(tmp_path, god=False)
    assert g.encounters_disabled is False


def test_toggling_god_flips_encounter_flag(tmp_path) -> None:
    g = _make_hex_game(tmp_path, god=False)
    assert g.encounters_disabled is False
    g.set_god_mode(True)
    assert g.encounters_disabled is True
    g.set_god_mode(False)
    assert g.encounters_disabled is False


# ---------------------------------------------------------------------------
# All rumors true under god mode
# ---------------------------------------------------------------------------


def test_god_mode_rumor_generator_forces_truth(tmp_path) -> None:
    g = _make_hex_game(tmp_path, god=True)
    rumors = generate_rumors_god_mode(g.hex_world, seed=1, count=6)
    assert rumors, "god-mode generator must still emit rumors"
    assert all(r.truth for r in rumors), (
        "god-mode rumors must all be true"
    )


def test_non_god_generator_still_mixes_truth(tmp_path) -> None:
    """Sanity: the normal generate_rumors continues to produce a
    mix under the same world -- god mode is the only flag that
    flips every rumor true."""
    from nhc.hexcrawl.rumor_pool import generate_rumors
    g = _make_hex_game(tmp_path, god=False)
    rumors = generate_rumors(g.hex_world, seed=1, count=6)
    truths = [r for r in rumors if r.truth]
    lies = [r for r in rumors if not r.truth]
    assert truths and lies, (
        "non-god generator should mix true and false rumors"
    )

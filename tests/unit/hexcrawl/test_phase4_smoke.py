"""Phase 4 integration smoke test.

Proves the debug surface composes: a god-mode hex game starts
with the fog lifted, encounter rolls flagged off, and every
rumor the god-mode generator emits is true. The MCP hex tools
then read the same world state over an autosave round-trip
(reveal_all_hexes is idempotent under an already-revealed
world; show_world_state returns the same dimensions the game
holds in memory).

Individual unit tests in test_god_mode.py and
debug_tools/test_hex_tools.py cover each slice; this case
wires them together end-to-end.
"""

from __future__ import annotations

import pytest

from nhc.core.autosave import autosave
from nhc.core.game import Game
from nhc.debug_tools.tools.hex_tools import (
    RevealAllHexesTool,
    ShowWorldStateTool,
)
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.mode import Difficulty, WorldType, GameMode
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


@pytest.mark.asyncio
async def test_phase4_god_mode_plus_mcp_tools(tmp_path, monkeypatch) -> None:
    # ── 1. Boot a god-mode hex game ─────────────────────────────
    g = Game(
        client=_FakeClient(),
        backend=None,
        style="classic",
        world_type=WorldType.HEXCRAWL, difficulty=Difficulty.EASY,
        save_dir=tmp_path,
        seed=7,
        god_mode=True,
    )
    g.initialize()

    # God mode does NOT auto-reveal fog; only the hub is revealed.
    assert g.hex_world is not None
    assert len(g.hex_world.revealed) < len(g.hex_world.cells)

    # Encounter rolls flag flipped by god mode.
    assert g.encounters_disabled is True

    # God-mode rumor generator never emits a lie.
    rumors = generate_rumors_god_mode(g.hex_world, seed=7, count=6)
    assert rumors
    assert all(r.truth for r in rumors)

    # ── 2. Round-trip via MCP tools on an autosave ─────────────
    save_path = tmp_path / "autosave.nhc"
    monkeypatch.setattr(
        "nhc.core.autosave._DEFAULT_PATH", save_path,
    )
    monkeypatch.setattr(
        "nhc.core.autosave._DEFAULT_DIR", tmp_path,
    )
    autosave(g)
    assert save_path.exists()

    # show_world_state reads the saved HexWorld back and reports
    # dimensions / day / time matching the live game.
    state = await ShowWorldStateTool().execute(path=str(save_path))
    assert state["width"] == g.hex_world.width
    assert state["height"] == g.hex_world.height
    assert state["day"] == g.hex_world.day
    assert state["time"] == g.hex_world.time.name.lower()
    assert len(state["cells"]) == len(g.hex_world.cells)

    # reveal_all_hexes lifts the remaining fog.
    reveal = await RevealAllHexesTool().execute(path=str(save_path))
    assert reveal["newly_revealed"] > 0
    assert reveal["total_revealed"] == reveal["total_cells"]

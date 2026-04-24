"""Regression: the flower → hex → flower round-trip must put the
player back on the sub-hex they exited from, not the default
entry sub-hex.

Before the fix, ``HexWorld.exit_flower()`` cleared both
``exploring_hex`` and ``exploring_sub_hex``, and the
``hex_explore`` handler re-entered the flower via
``entry_sub_hex_for_edge(last_entry_edge[macro])``. That picks
the sub-hex the player would have *first entered* the flower
from -- usually the center -- ignoring wherever they stepped
to during the visit. So pressing Shift-L on sub-hex (1, 0)
dropped the player on the macro map and a subsequent x / Explore
snapped them back to (0, 0), losing position.

Two tests:

- Unit-level pin: ``exit_flower`` stashes the
  ``exploring_sub_hex`` into the per-macro dict.
- Integration: hex_session's ``hex_explore`` intent prefers the
  stashed sub-hex over the entry-edge fallback.

See ``design/views.md`` for the five-view hierarchy.
"""

from __future__ import annotations

import pytest

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import HexWorld


def _bare_hex_world() -> HexWorld:
    """HexWorld needs pack_id / seed / width / height to
    construct. This test only exercises the flower state
    pointers, not cell generation, so we pass minimal values."""
    return HexWorld(pack_id="t", seed=1, width=1, height=1)


def test_exit_flower_stashes_exploring_sub_hex() -> None:
    w = _bare_hex_world()
    macro = HexCoord(0, 0)
    # Synthesise a visit: player is inside the flower at sub (1, 0).
    w.exploring_hex = macro
    w.exploring_sub_hex = HexCoord(1, 0)
    w.exit_flower()
    # Both state pointers are cleared for the macro-map render path.
    assert w.exploring_hex is None
    assert w.exploring_sub_hex is None
    # But the per-macro stash remembers where we were, so a later
    # hex_explore on the same macro can restore it.
    assert w.last_sub_hex_by_macro.get(macro) == HexCoord(1, 0), (
        "exit_flower must remember the sub-hex the player was on "
        "before clearing the pointers; otherwise the flower -> "
        "hex -> flower round-trip loses position"
    )


def test_exit_flower_without_sub_hex_is_noop_for_stash() -> None:
    """Calling exit_flower while already on the macro map (both
    pointers None) should not poison the stash."""
    w = _bare_hex_world()
    w.exploring_hex = None
    w.exploring_sub_hex = None
    w.exit_flower()
    assert w.last_sub_hex_by_macro == {}


@pytest.mark.asyncio
async def test_hex_explore_round_trip_preserves_sub_hex_position(
    tmp_path,
) -> None:
    """Integration: flower -> hex -> flower via the hex_session
    dispatcher must restore the player to the sub-hex they
    exited from, not the default entry edge.

    Before the fix: exploring_sub_hex was cleared by
    exit_flower; hex_explore re-entered using
    entry_sub_hex_for_edge(last_entry_edge[coord]) which is the
    center when the player hasn't crossed an edge. So stepping
    around the flower to, say, (1, 0), pressing L, then
    pressing x on the overland snapped you back to (0, 0).
    """
    from unittest.mock import AsyncMock

    from nhc.core.game import Game
    from nhc.entities.registry import EntityRegistry
    from nhc.hexcrawl.mode import GameMode
    from nhc.i18n import init as i18n_init

    i18n_init("en")
    EntityRegistry.discover_all()

    class _FakeClient:
        game_mode = "classic"; lang = "en"; edge_doors = False
        messages: list[str] = []

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)

            def _sync(*a, **kw):
                return None

            return _sync

    g = Game(
        client=_FakeClient(),
        backend=None,
        style="classic",
        world_type=GameMode.HEX_EASY.world_type,
        difficulty=GameMode.HEX_EASY.difficulty,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()

    # HEX_EASY seeds the player inside the hub's flower at the
    # center; "wander" to a non-center sub-hex so we have
    # something non-trivial to remember.
    macro = g.hex_world.exploring_hex
    assert macro is not None
    g.hex_world.exploring_sub_hex = HexCoord(1, 0)

    # Fire the flower_exit intent through the real dispatcher.
    g.renderer.get_input = AsyncMock(return_value=("flower_exit", None))
    outcome = await g._hex._process_flower_turn()
    assert outcome == "moved"
    assert g.hex_world.exploring_hex is None, (
        "flower_exit should clear the flower pointers so the "
        "macro map renders"
    )
    # The stash now remembers where we were.
    assert g.hex_world.last_sub_hex_by_macro.get(macro) == HexCoord(1, 0)

    # Bounce back into the same hex via hex_explore.
    g.renderer.get_input = AsyncMock(return_value=("hex_explore", None))
    outcome = await g._hex._process_hex_turn()
    assert outcome == "moved"
    assert g.hex_world.exploring_hex == macro
    # Position must be preserved, not the default center.
    assert g.hex_world.exploring_sub_hex == HexCoord(1, 0), (
        "hex_explore on the same macro hex must prefer the "
        "stashed sub-hex over entry_sub_hex_for_edge; "
        "otherwise the round-trip loses position"
    )

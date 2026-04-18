"""Pure-function layer for the hex-mode MCP debug tools.

Each helper takes a :class:`HexWorld` and applies a single
debug-ish transform (reveal-all, teleport, seed a feature,
etc.), returning either a primitive result or a serializable
dict. The MCP tool wrappers in :mod:`nhc.debug_tools.tools.hex`
(thin JSON marshalling) call into these; keeping the logic as
plain Python functions makes the behaviour unit-testable
without spinning up a server or touching the filesystem.
"""

from __future__ import annotations

from typing import Any

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.encounter import DEFAULT_BIOME_POOLS
from nhc.hexcrawl.encounter_pipeline import Encounter
from nhc.hexcrawl.model import (
    Biome,
    DungeonRef,
    HexFeatureType,
    HexWorld,
    Rumor,
)


# ---------------------------------------------------------------------------
# Fog / reveal
# ---------------------------------------------------------------------------


def reveal_all_hexes(world: HexWorld) -> int:
    """Add every in-shape cell to ``world.revealed``.

    Returns the count of newly-revealed cells so the caller can
    report what changed.
    """
    before = len(world.revealed)
    for coord in world.cells:
        world.revealed.add(coord)
    return len(world.revealed) - before


# ---------------------------------------------------------------------------
# Teleport
# ---------------------------------------------------------------------------


def teleport_hex(world: HexWorld, target: HexCoord) -> bool:
    """Treat ``target`` as the player's new location (the game
    caller is responsible for updating its own
    ``hex_player_position`` with this coord). The cell plus its
    neighbours are revealed so the debug teleport doubles as a
    scrying window, and the target joins
    :attr:`HexWorld.visited` because the player is there now --
    downstream logic that keys off "has the player been here"
    should see a teleport the same as a normal step.

    Returns ``True`` when the target is a valid in-shape hex,
    ``False`` when it falls outside the map.
    """
    if not world.is_in_shape(target):
        return False
    world.visit(target)
    return True


# ---------------------------------------------------------------------------
# Force an encounter
# ---------------------------------------------------------------------------


def force_encounter(
    biome: Biome,
    creatures: list[str] | None = None,
) -> Encounter:
    """Build an :class:`Encounter` without needing an RNG roll.

    When ``creatures`` is omitted the default biome pack is
    copied verbatim so the caller sees the full pool instead of
    a random sample; the real pipeline's 2-4 pack trimming is
    the game's job, not the debug hook's.
    """
    if creatures is None:
        pool = DEFAULT_BIOME_POOLS.get(
            biome, DEFAULT_BIOME_POOLS[Biome.GREENLANDS],
        )
        creatures_out = list(pool)
    else:
        creatures_out = list(creatures)
    return Encounter(biome=biome, creatures=creatures_out)


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def show_world_state(
    world: HexWorld,
    player: HexCoord,
) -> dict[str, Any]:
    """Return a JSON-friendly snapshot of the hex world.

    Mirrors the shape of the web client's ``state_hex`` payload
    but with extra debug-facing fields (full cell list including
    unrevealed, rumors, cleared / visited sets).
    """
    cells = [
        {
            "q": coord.q,
            "r": coord.r,
            "biome": cell.biome.value,
            "feature": cell.feature.value,
            "revealed": coord in world.revealed,
            "visited": coord in world.visited,
            "cleared": coord in world.cleared,
        }
        for coord, cell in sorted(
            world.cells.items(), key=lambda kv: (kv[0].q, kv[0].r),
        )
    ]
    rumors = [
        {
            "id": r.id,
            "text": r.text,
            "truth": r.truth,
            "reveals": (
                {"q": r.reveals.q, "r": r.reveals.r}
                if r.reveals is not None else None
            ),
        }
        for r in world.active_rumors
    ]
    return {
        "pack_id": world.pack_id,
        "seed": world.seed,
        "width": world.width,
        "height": world.height,
        "day": world.day,
        "time": world.time.name.lower(),
        "player": {"q": player.q, "r": player.r},
        "cells": cells,
        "rumors": rumors,
    }


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def advance_day_clock(world: HexWorld, segments: int) -> None:
    """Advance the overland clock by ``segments`` half-days.

    Thin wrapper around :meth:`HexWorld.advance_clock` so the
    MCP tool surface reads as "advance_day_clock" in the tool
    list; keeps the debug vocabulary distinct from in-game
    action names.
    """
    world.advance_clock(segments)


# ---------------------------------------------------------------------------
# Rumor truth flip
# ---------------------------------------------------------------------------


def set_rumor_truth(
    world: HexWorld,
    rumor_id: str,
    truth: bool,
) -> bool:
    """Flip the ``truth`` field on a rumor in
    :attr:`HexWorld.active_rumors` identified by ``rumor_id``.

    Returns ``True`` when the rumor was found and updated,
    ``False`` when no matching rumor is currently active.
    """
    for rumor in world.active_rumors:
        if rumor.id == rumor_id:
            rumor.truth = truth
            return True
    return False


# ---------------------------------------------------------------------------
# Cleared-state flips
# ---------------------------------------------------------------------------


def clear_dungeon_at(world: HexWorld, coord: HexCoord) -> bool:
    """Mark ``coord`` as a cleared dungeon hex.

    Returns ``False`` when the coord is outside the map shape;
    ``True`` after the cleared flag has been added (idempotent
    -- calling twice is a no-op on the second call).
    """
    if not world.is_in_shape(coord):
        return False
    world.cleared.add(coord)
    return True


def seed_dungeon_at(
    world: HexWorld,
    coord: HexCoord,
    feature: HexFeatureType,
    template: str,
    depth: int = 1,
) -> bool:
    """Write a feature + :class:`DungeonRef` at ``coord``.

    Useful for reproducing a bug report against a specific hex
    without needing a custom seed. Returns ``False`` when the
    target is out of shape; ``True`` after the cell has been
    updated in place.
    """
    if not world.is_in_shape(coord):
        return False
    cell = world.cells[coord]
    cell.feature = feature
    cell.dungeon = DungeonRef(template=template, depth=depth)
    return True


# ---------------------------------------------------------------------------
# Rumor seeding (useful companion to set_rumor_truth)
# ---------------------------------------------------------------------------


def seed_rumor(
    world: HexWorld,
    rumor: Rumor,
) -> None:
    """Append ``rumor`` to :attr:`HexWorld.active_rumors`.

    Re-exported from this module so debug scripts can stage a
    specific rumor (e.g. "what if the player's last inn visit
    generated THIS lie?") without reaching into the rumors
    module directly.
    """
    world.active_rumors.append(rumor)

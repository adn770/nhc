"""Vault room placement for BSP dungeons."""

from __future__ import annotations

import logging
import random

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.model import Level, Rect, RectShape, Room, Terrain, Tile

logger = logging.getLogger(__name__)


def _place_vaults(
    level: Level, rng: random.Random,
    params: GenerationParams,
) -> list[Rect]:
    """Place 2x2 / 3x2 disconnected vault rooms in void space.

    Vaults are tiny treasure caches unreachable from the main
    dungeon.  Players can only get in by digging through a
    wall.  Each vault is added to ``level.rooms`` with a
    ``"vault"`` tag but is never inserted into the BSP
    adjacency graph, so corridor carving and flood-fill
    reconnection leave it untouched.
    """
    target = 1 + params.depth // 2 + rng.randint(0, 1)
    sizes = [(2, 2), (3, 2), (2, 3)]
    placed: list[Rect] = []
    attempts = 0
    max_attempts = 300
    # Buffer in tiles around the vault: the inner ring becomes
    # the vault's own wall, the outer ring stays VOID so the
    # new walls never sit directly next to an existing corridor
    # or room wall (which would close the corridor into a
    # walled tunnel).
    BUFFER = 2

    while len(placed) < target and attempts < max_attempts:
        attempts += 1
        vw, vh = rng.choice(sizes)
        vx = rng.randint(
            BUFFER + 1, level.width - vw - BUFFER - 2,
        )
        vy = rng.randint(
            BUFFER + 1, level.height - vh - BUFFER - 2,
        )

        # The bounding box plus a BUFFER-tile border must be
        # entirely VOID — guarantees a clean wall ring and
        # prevents the new wall from sealing a neighbouring
        # corridor on both sides.
        box_ok = True
        for dy in range(-BUFFER, vh + BUFFER):
            if not box_ok:
                break
            for dx in range(-BUFFER, vw + BUFFER):
                t = level.tile_at(vx + dx, vy + dy)
                if t is None or t.terrain != Terrain.VOID:
                    box_ok = False
                    break
        if not box_ok:
            continue

        # Carve the vault interior as plain FLOOR.
        for dy in range(vh):
            for dx in range(vw):
                level.tiles[vy + dy][vx + dx] = Tile(
                    terrain=Terrain.FLOOR,
                )
        # Wrap it in a solid wall ring (the border was VOID).
        for dy in range(-1, vh + 1):
            for dx in range(-1, vw + 1):
                if 0 <= dx < vw and 0 <= dy < vh:
                    continue
                level.tiles[vy + dy][vx + dx] = Tile(
                    terrain=Terrain.WALL,
                )

        rect = Rect(vx, vy, vw, vh)
        placed.append(rect)
        level.rooms.append(Room(
            id=f"vault_{len(placed)}",
            rect=rect,
            shape=RectShape(),
            tags=["vault"],
        ))

    if placed:
        logger.info(
            "Placed %d vault(s) (target=%d, attempts=%d)",
            len(placed), target, attempts,
        )
    return placed

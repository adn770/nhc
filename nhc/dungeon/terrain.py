"""Cellular automata terrain generation for water and vegetation.

Applies organic water/grass patches to an already-carved dungeon level.
Adapted from Pixel Dungeon's Patch.java algorithm.
"""

from __future__ import annotations

import logging
import random

logger = logging.getLogger(__name__)

from nhc.dungeon.model import Level, Terrain

# Theme → (water_seed, water_iters, grass_seed, grass_iters)
THEME_PARAMS: dict[str, tuple[float, int, float, int]] = {
    "crypt":   (0.35, 4, 0.20, 3),
    "cave":    (0.45, 6, 0.35, 3),
    "sewer":   (0.50, 5, 0.40, 4),
    "castle":  (0.25, 3, 0.15, 2),
    "forest":  (0.30, 4, 0.55, 5),
    "dungeon": (0.35, 4, 0.25, 3),
    "abyss":   (0.55, 6, 0.05, 2),
}

# Level feelings override seed probabilities
FEELINGS = ["normal", "flooded", "overgrown", "barren"]


def apply_terrain(level: Level, rng: random.Random) -> None:
    """Apply water patches to a level using cellular automata.

    Only places water on floor tiles that are NOT corridors, stairs,
    doors, or traps.
    """
    theme = level.metadata.theme if level.metadata else "dungeon"
    params = THEME_PARAMS.get(theme, THEME_PARAMS["dungeon"])
    water_seed, water_iters, grass_seed, grass_iters = params

    # Roll for level feeling (10% chance on depth > 1)
    feeling = "normal"
    if level.depth > 1 and rng.random() < 0.10:
        feeling = rng.choice(FEELINGS)

    # Store feeling on level metadata
    if level.metadata:
        level.metadata.feeling = feeling

    if feeling == "flooded":
        water_seed = min(1.0, water_seed + 0.15)
    elif feeling == "overgrown":
        grass_seed = min(1.0, grass_seed + 0.15)
    elif feeling == "barren":
        return  # No terrain features

    # Generate water mask
    water = _cellular_automata(
        level.width, level.height, water_seed, water_iters, rng,
    )

    # Apply water (only on bare floor tiles, skip corridors)
    for y in range(1, level.height - 1):
        for x in range(1, level.width - 1):
            tile = level.tiles[y][x]
            if (tile.terrain == Terrain.FLOOR
                    and not tile.feature
                    and not tile.is_corridor
                    and water[y][x]):
                tile.terrain = Terrain.WATER

    # Generate grass mask
    if grass_seed > 0:
        grass = _cellular_automata(
            level.width, level.height, grass_seed, grass_iters, rng,
        )
        for y in range(1, level.height - 1):
            for x in range(1, level.width - 1):
                tile = level.tiles[y][x]
                if (tile.terrain == Terrain.FLOOR
                        and not tile.feature
                        and not tile.is_corridor
                        and grass[y][x]):
                    tile.terrain = Terrain.GRASS

    water_count = sum(
        1 for row in level.tiles for t in row
        if t.terrain == Terrain.WATER
    )
    grass_count = sum(
        1 for row in level.tiles for t in row
        if t.terrain == Terrain.GRASS
    )
    logger.info(
        "Terrain: theme=%s feeling=%s water=%.2f grass=%.2f"
        " → %d water, %d grass tiles",
        theme, feeling, water_seed, grass_seed, water_count, grass_count,
    )


def _cellular_automata(
    width: int,
    height: int,
    seed_prob: float,
    iterations: int,
    rng: random.Random,
) -> list[list[bool]]:
    """Run cellular automata and return a boolean grid.

    Algorithm:
    1. Seed: each cell ON with probability seed_prob
    2. N iterations: cell ON if (was OFF and ≥5 neighbors ON) or
       (was ON and ≥4 neighbors ON)
    """
    # Initialize
    grid = [
        [rng.random() < seed_prob for _ in range(width)]
        for _ in range(height)
    ]

    # Iterate
    for _ in range(iterations):
        new_grid = [[False] * width for _ in range(height)]
        for y in range(1, height - 1):
            for x in range(1, width - 1):
                count = _count_neighbors(grid, x, y)
                if grid[y][x]:
                    new_grid[y][x] = count >= 4
                else:
                    new_grid[y][x] = count >= 5
        grid = new_grid

    return grid


def _count_neighbors(grid: list[list[bool]], x: int, y: int) -> int:
    """Count ON neighbors in a 3×3 area (excluding center)."""
    count = 0
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            if dx == 0 and dy == 0:
                continue
            ny, nx = y + dy, x + dx
            if 0 <= ny < len(grid) and 0 <= nx < len(grid[0]):
                if grid[ny][nx]:
                    count += 1
    return count

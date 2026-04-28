"""Surface-feature plumbing for the floor IR pipeline.

The legacy procedural painters (well / fountain / tree / bush
fragment helpers and their TileDecorator wrappers) were ported
to Rust across §8 steps 13-16; the structured WellFeatureOp /
FountainFeatureOp / TreeFeatureOp / BushFeatureOp variants own
the per-shape geometry. The Python emitter only needs the
grove-detection helper to feed TreeFeatureOp's grove split.
"""

from __future__ import annotations

from nhc.dungeon.model import Level


def _connected_tree_groves(
    level: Level,
) -> list[frozenset[tuple[int, int]]]:
    """4-adjacency BFS over ``tile.feature == "tree"``.

    Returns one frozenset of ``(tx, ty)`` tuples per connected
    grove. Diagonal-only neighbours stay separate. Consumed by
    :func:`nhc.rendering._floor_layers._emit_surface_features_ir`
    to split tree tiles into singletons / pairs (free trees) and
    groves (3+ tiles fused into one canopy union by the Rust
    port).
    """
    height = level.height
    width = level.width
    visited: list[list[bool]] = [
        [False] * width for _ in range(height)
    ]
    groves: list[frozenset[tuple[int, int]]] = []
    for sy in range(height):
        for sx in range(width):
            if visited[sy][sx]:
                continue
            if level.tiles[sy][sx].feature != "tree":
                continue
            grove: set[tuple[int, int]] = set()
            stack: list[tuple[int, int]] = [(sx, sy)]
            while stack:
                cx, cy = stack.pop()
                if cx < 0 or cy < 0 or cx >= width or cy >= height:
                    continue
                if visited[cy][cx]:
                    continue
                if level.tiles[cy][cx].feature != "tree":
                    continue
                visited[cy][cx] = True
                grove.add((cx, cy))
                stack.append((cx + 1, cy))
                stack.append((cx - 1, cy))
                stack.append((cx, cy + 1))
                stack.append((cx, cy - 1))
            if grove:
                groves.append(frozenset(grove))
    return groves

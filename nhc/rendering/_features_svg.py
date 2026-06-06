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
    # World-coord flood fill. ``visited`` is a coordinate set rather
    # than a positional buffer so the scan works regardless of the
    # grid's origin (a building floor offsets it); out-of-bounds
    # neighbours surface as ``tile_at`` returning ``None``.
    visited: set[tuple[int, int]] = set()
    groves: list[frozenset[tuple[int, int]]] = []
    for sx, sy, tile in level.iter_world():
        if (sx, sy) in visited:
            continue
        if tile.feature != "tree":
            continue
        grove: set[tuple[int, int]] = set()
        stack: list[tuple[int, int]] = [(sx, sy)]
        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in visited:
                continue
            nb = level.tile_at(cx, cy)
            if nb is None or nb.feature != "tree":
                continue
            visited.add((cx, cy))
            grove.add((cx, cy))
            stack.append((cx + 1, cy))
            stack.append((cx - 1, cy))
            stack.append((cx, cy + 1))
            stack.append((cx, cy - 1))
        if grove:
            groves.append(frozenset(grove))
    return groves

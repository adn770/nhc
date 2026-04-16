"""Mini-dungeon encounter arena generator (M-2.5).

On the Fight branch of a hex-step encounter, the game pushes a
one-room "arena" Level onto the floor cache so the regular
combat pipeline can resolve the fight. The arena is small,
biome-themed, seeded reproducibly from the hex coord, and
pre-populated with the chosen foes.
"""

from __future__ import annotations

from nhc.dungeon.model import Terrain
from nhc.hexcrawl.encounter import (
    ARENA_TAG,
    generate_encounter_arena,
)
from nhc.hexcrawl.model import Biome


# ---------------------------------------------------------------------------
# Shape and entry
# ---------------------------------------------------------------------------


def test_arena_has_positive_dimensions_and_single_room() -> None:
    level = generate_encounter_arena(seed=1, biome=Biome.GREENLANDS)
    assert level.width > 0
    assert level.height > 0
    assert len(level.rooms) == 1
    room = level.rooms[0]
    assert ARENA_TAG in room.tags


def test_arena_has_stairs_up_entry() -> None:
    level = generate_encounter_arena(seed=1, biome=Biome.FOREST)
    entries = [
        (x, y)
        for y in range(level.height)
        for x in range(level.width)
        if (tile := level.tile_at(x, y)) is not None
        and tile.feature == "stairs_up"
    ]
    assert len(entries) == 1, (
        f"arena must have exactly one stairs_up tile, got {entries}"
    )
    x, y = entries[0]
    assert level.tile_at(x, y).terrain is Terrain.FLOOR


def test_arena_room_floor_is_connected() -> None:
    """BFS from the entry tile reaches every FLOOR tile inside the
    arena — no disconnected pockets."""
    from collections import deque
    level = generate_encounter_arena(seed=3, biome=Biome.MOUNTAIN)

    start = next(
        (x, y)
        for y in range(level.height)
        for x in range(level.width)
        if (tile := level.tile_at(x, y)) is not None
        and tile.feature == "stairs_up"
    )
    seen = {start}
    frontier: deque[tuple[int, int]] = deque([start])
    while frontier:
        cx, cy = frontier.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = cx + dx, cy + dy
            if not (0 <= nx < level.width and 0 <= ny < level.height):
                continue
            t = level.tile_at(nx, ny)
            if t is None or t.terrain is not Terrain.FLOOR:
                continue
            if (nx, ny) in seen:
                continue
            seen.add((nx, ny))
            frontier.append((nx, ny))

    floors = {
        (x, y)
        for y in range(level.height)
        for x in range(level.width)
        if (tile := level.tile_at(x, y)) is not None
        and tile.terrain is Terrain.FLOOR
    }
    assert seen == floors, (
        f"arena floor not fully connected: "
        f"{len(floors - seen)} unreachable tiles"
    )


# ---------------------------------------------------------------------------
# Creature placement
# ---------------------------------------------------------------------------


def test_arena_places_supplied_creatures() -> None:
    level = generate_encounter_arena(
        seed=1, biome=Biome.GREENLANDS,
        creatures=("goblin", "goblin", "kobold"),
    )
    placed_ids = [p.entity_id for p in level.entities
                  if p.entity_type == "creature"]
    assert sorted(placed_ids) == ["goblin", "goblin", "kobold"]
    # Every placement lands on a FLOOR tile and isn't on the
    # entry tile (so the player doesn't land on a foe).
    for p in level.entities:
        t = level.tile_at(p.x, p.y)
        assert t is not None and t.terrain is Terrain.FLOOR
        assert t.feature != "stairs_up", (
            f"creature {p.entity_id} placed on entry tile"
        )


def test_arena_defaults_to_biome_creature_pool() -> None:
    """Omitting creatures falls back to a biome-keyed pool, seeded
    from ``seed`` so the same hex produces the same mob mix."""
    level = generate_encounter_arena(seed=7, biome=Biome.FOREST)
    creatures = [p for p in level.entities if p.entity_type == "creature"]
    assert creatures, "default pool should place at least one creature"


# ---------------------------------------------------------------------------
# Seed reproducibility
# ---------------------------------------------------------------------------


def test_arena_generator_seed_reproducibility() -> None:
    a = generate_encounter_arena(seed=42, biome=Biome.DRYLANDS)
    b = generate_encounter_arena(seed=42, biome=Biome.DRYLANDS)
    assert a.width == b.width and a.height == b.height
    for y in range(a.height):
        for x in range(a.width):
            assert (
                a.tile_at(x, y).terrain == b.tile_at(x, y).terrain
            )
    assert [(p.entity_id, p.x, p.y) for p in a.entities] == \
           [(p.entity_id, p.x, p.y) for p in b.entities]


def test_arena_different_biomes_carry_distinct_theme() -> None:
    a = generate_encounter_arena(seed=1, biome=Biome.MOUNTAIN)
    b = generate_encounter_arena(seed=1, biome=Biome.ICELANDS)
    assert a.metadata.theme != b.metadata.theme, (
        "arena metadata.theme should reflect the source biome"
    )

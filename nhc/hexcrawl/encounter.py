"""Mini-dungeon "arena" generator for overland encounters.

When the player picks *Fight* on an encounter prompt the game
pushes a small single-room Level onto the floor cache so the
regular combat system can resolve the skirmish. Exiting the
arena pops back to the overland via the same hex exit path as a
regular dungeon visit.

The arena is intentionally simple: a flat rectangular room with
the player entering at the west edge (``stairs_up``) and the
foes clustered on the east side. Biomes only tint the metadata
(``theme`` / ``ambient``) today -- later milestones can swap in
biome-specific tiles, but the combat engine doesn't care about
that, so v1 keeps the generator stable.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Sequence

from nhc.dungeon.model import (
    EntityPlacement,
    Level,
    LevelMetadata,
    Rect,
    RectShape,
    Room,
    Terrain,
    Tile,
)
from nhc.hexcrawl.model import Biome


# Room tag used by Game wiring and tests to identify the arena.
ARENA_TAG = "arena"

# Fixed shape of the arena. Large enough to let a 2-henchman
# party manoeuvre against a pack, small enough that combat stays
# punchy.
_ARENA_WIDTH = 15
_ARENA_HEIGHT = 9

# Room interior (inclusive): leaves a one-tile WALL border so the
# combat system's adjacency / shape checks behave predictably.
_ROOM_RECT = Rect(x=1, y=1, width=_ARENA_WIDTH - 2, height=_ARENA_HEIGHT - 2)

# Player entry tile: west-middle of the interior.
_ENTRY = (_ROOM_RECT.x, _ROOM_RECT.y + _ROOM_RECT.height // 2)


# Default creature pools per biome. Picked to feel thematically
# right without reaching into the full dungeon CREATURE_POOLS
# (those are difficulty-keyed, not biome-keyed).
DEFAULT_BIOME_POOLS: dict[Biome, tuple[str, ...]] = {
    Biome.GREENLANDS: ("goblin", "kobold", "giant_rat"),
    Biome.DRYLANDS: ("kobold", "gnoll", "bandit"),
    Biome.SANDLANDS: ("kobold", "giant_centipede", "giant_scorpion"),
    Biome.ICELANDS: ("wolf", "winter_wolf", "skeleton"),
    Biome.DEADLANDS: ("skeleton", "zombie", "ghoul"),
    Biome.FOREST: ("goblin", "giant_bee", "giant_centipede"),
    Biome.MOUNTAIN: ("kobold", "hobgoblin", "wolf"),
    # Hills blend mountain bandits with low-hills vermin; marsh
    # and swamp lean wet + undead (swamp heavier on the dead).
    Biome.HILLS: ("goblin", "hobgoblin", "bandit"),
    Biome.MARSH: ("giant_leech", "frogman", "giant_centipede"),
    Biome.SWAMP: ("zombie", "ghoul", "giant_leech"),
}


def _blank_tiles() -> list[list[Tile]]:
    """Start with solid WALL; the room painter carves the interior."""
    return [
        [Tile(terrain=Terrain.WALL) for _ in range(_ARENA_WIDTH)]
        for _ in range(_ARENA_HEIGHT)
    ]


def _carve_room(tiles: list[list[Tile]], rect: Rect) -> None:
    for y in range(rect.y, rect.y + rect.height):
        for x in range(rect.x, rect.x + rect.width):
            tiles[y][x].terrain = Terrain.FLOOR


def _default_pool(biome: Biome, rng: random.Random) -> list[str]:
    """Choose a small default mob pack for ``biome``.

    Picks a pack of 2-4 creatures from the biome list. Always
    non-empty so the arena never boots with zero foes.
    """
    pool = DEFAULT_BIOME_POOLS.get(biome, DEFAULT_BIOME_POOLS[Biome.GREENLANDS])
    count = rng.randint(2, 4)
    return [rng.choice(pool) for _ in range(count)]


def generate_encounter_arena(
    seed: int,
    biome: Biome,
    creatures: Iterable[str] | None = None,
    arena_id: str = "encounter",
) -> Level:
    """Return a single-room arena :class:`Level` for a hex-step fight.

    Parameters
    ----------
    seed
        Mixes into creature layout / default pool draw so the
        same hex encounter replays identically.
    biome
        Drives :attr:`LevelMetadata.theme` / ``ambient`` and the
        fallback creature pool when ``creatures`` is omitted.
    creatures
        Explicit list of creature ids to place. When ``None`` the
        generator draws a small pack from
        :data:`DEFAULT_BIOME_POOLS`.
    arena_id
        Identifier used as :attr:`Level.id` / :attr:`Level.name`
        and as the prefix for room IDs. Distinct per encounter so
        the floor cache key can point at it unambiguously.
    """
    rng = random.Random(seed)
    if creatures is None:
        creature_list: Sequence[str] = _default_pool(biome, rng)
    else:
        creature_list = list(creatures)

    tiles = _blank_tiles()
    _carve_room(tiles, _ROOM_RECT)

    # Player entry.
    ex, ey = _ENTRY
    tiles[ey][ex].feature = "stairs_up"

    room = Room(
        id=f"{arena_id}_room_0",
        rect=_ROOM_RECT,
        shape=RectShape(),
        tags=[ARENA_TAG, biome.value],
        description=f"{biome.value} arena",
    )

    # Scatter creatures on the east half of the room, randomised
    # but excluding the entry column so the player spawns clear.
    entities: list[EntityPlacement] = []
    east_min_x = _ROOM_RECT.x + _ROOM_RECT.width // 2
    candidates = [
        (x, y)
        for y in range(_ROOM_RECT.y, _ROOM_RECT.y + _ROOM_RECT.height)
        for x in range(east_min_x, _ROOM_RECT.x + _ROOM_RECT.width)
        if (x, y) != (ex, ey)
    ]
    rng.shuffle(candidates)
    for creature_id, (cx, cy) in zip(creature_list, candidates):
        entities.append(EntityPlacement(
            entity_type="creature", entity_id=creature_id,
            x=cx, y=cy,
        ))

    return Level(
        id=arena_id,
        name=arena_id,
        depth=1,
        width=_ARENA_WIDTH,
        height=_ARENA_HEIGHT,
        tiles=tiles,
        rooms=[room],
        corridors=[],
        entities=entities,
        metadata=LevelMetadata(
            theme=f"arena_{biome.value}",
            ambient=biome.value,
        ),
    )

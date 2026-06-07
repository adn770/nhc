"""Town event director: scheduled ambient spectacle.

On town entry the director rolls deterministic daytime spectacle —
a market day (extra vendors and a crowd by the plaza) or a procession
crossing the town — returning log-line keys plus live extra entity
placements tagged ``event_spawn``. The caller seeds the RNG from the
site seed, day and segment so the same visit reproduces, while a
different day or hour looks different. Spectacle never fires at night.
See ``design/town_life.md``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from nhc.dungeon.model import EntityPlacement, Level, SurfaceType
from nhc.hexcrawl.model import TimeOfDay

# Per-size chance a market day is underway (daytime only). Hamlets
# have no market.
MARKET_DAY_CHANCE: dict[str, float] = {
    "village": 0.20,
    "town": 0.35,
    "city": 0.45,
}
MARKET_VENDOR_RANGE: dict[str, tuple[int, int]] = {
    "village": (1, 2),
    "town": (2, 3),
    "city": (3, 5),
}
MARKET_CROWD_RANGE: dict[str, tuple[int, int]] = {
    "village": (2, 4),
    "town": (4, 6),
    "city": (6, 10),
}
# Processions are rarer and can roll through any daylight segment.
PROCESSION_CHANCE: dict[str, float] = {
    "village": 0.06,
    "town": 0.09,
    "city": 0.12,
}
PROCESSION_LENGTH_RANGE = (3, 6)

_DAY_SEGMENTS = (TimeOfDay.MORNING, TimeOfDay.MIDDAY, TimeOfDay.EVENING)
_MARKET_SEGMENTS = (TimeOfDay.MORNING, TimeOfDay.MIDDAY)


@dataclass
class TownEventResult:
    """What the director staged this visit: log-line keys plus live
    entity placements (already tagged ``event_spawn``)."""
    messages: list[str] = field(default_factory=list)
    placements: list[EntityPlacement] = field(default_factory=list)


def _open_street_tiles(level: Level) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for x, y, tile in level.iter_world():
        if tile.surface_type != SurfaceType.STREET:
            continue
        if not tile.walkable or tile.feature is not None:
            continue
        out.append((x, y))
    return out


def _event_creature(
    entity_id: str, x: int, y: int, anchor: tuple[int, int] | None,
    weight: float,
) -> EntityPlacement:
    extra: dict = {"event_spawn": True}
    if anchor is not None:
        extra["daily_routine"] = {
            "workplace": list(anchor),
            "home": list(anchor),
            "weight": weight,
        }
    return EntityPlacement(
        entity_type="creature", entity_id=entity_id, x=x, y=y, extra=extra,
    )


def _market_day(
    level: Level, size_class: str, rng: random.Random,
) -> list[EntityPlacement]:
    cands = _open_street_tiles(level)
    if not cands:
        return []
    cx, cy = level.width // 2, level.height // 2
    cands.sort(key=lambda s: (s[0] - cx) ** 2 + (s[1] - cy) ** 2)
    anchor = cands[0]
    pool = cands[: max(8, len(cands) // 4)]
    rng.shuffle(pool)

    n_vendor = rng.randint(*MARKET_VENDOR_RANGE[size_class])
    n_crowd = rng.randint(*MARKET_CROWD_RANGE[size_class])
    placements: list[EntityPlacement] = []
    used: set[tuple[int, int]] = set()

    def _spawn(entity_id: str, weight: float) -> None:
        for spot in pool:
            if spot in used:
                continue
            used.add(spot)
            placements.append(
                _event_creature(entity_id, spot[0], spot[1], anchor, weight),
            )
            return

    for _ in range(n_vendor):
        _spawn("market_vendor", 0.85)
    for _ in range(n_crowd):
        _spawn("villager", 0.5)
    return placements


def _procession(
    level: Level, rng: random.Random,
) -> list[EntityPlacement]:
    cy = level.height // 2
    row = [
        (x, cy) for x in range(level.width)
        if (tile := level.tile_at(x, cy)) is not None
        and tile.surface_type == SurfaceType.STREET
        and tile.walkable and tile.feature is None
    ]
    if len(row) < PROCESSION_LENGTH_RANGE[0]:
        return []
    length = min(rng.randint(*PROCESSION_LENGTH_RANGE), len(row))
    start = rng.randint(0, len(row) - length)
    line = row[start: start + length]
    # Walk the line as a loose errand crowd (no anchor — they drift).
    return [
        _event_creature("villager", x, y, None, 0.0)
        for (x, y) in line
    ]


def roll_town_events(
    level: Level,
    size_class: str,
    segment: TimeOfDay,
    rng: random.Random,
) -> TownEventResult:
    """Roll this visit's spectacle for a town of ``size_class`` at
    ``segment``. Deterministic in ``rng``."""
    result = TownEventResult()
    if segment not in _DAY_SEGMENTS:
        return result

    if (segment in _MARKET_SEGMENTS
            and rng.random() < MARKET_DAY_CHANCE.get(size_class, 0.0)):
        spawns = _market_day(level, size_class, rng)
        if spawns:
            result.messages.append("town.event.market_day")
            result.placements.extend(spawns)

    if rng.random() < PROCESSION_CHANCE.get(size_class, 0.0):
        spawns = _procession(level, rng)
        if spawns:
            result.messages.append("town.event.procession")
            result.placements.extend(spawns)

    return result

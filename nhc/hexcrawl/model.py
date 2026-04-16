"""HexCell, HexWorld, and the core hexcrawl enums.

The model is intentionally pure data: no dependency on the ECS,
rendering, or save layers. The :class:`HexWorld` aggregates per-hex
cells with the player-progress sets (revealed / visited / cleared /
looted), the day clock, the active rumour list, and the expedition
party.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from nhc.hexcrawl.coords import HexCoord, in_bounds, neighbors


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Biome(Enum):
    GREENLANDS = "greenlands"
    DRYLANDS = "drylands"
    SANDLANDS = "sandlands"
    ICELANDS = "icelands"
    DEADLANDS = "deadlands"
    FOREST = "forest"
    MOUNTAIN = "mountain"


class HexFeatureType(Enum):
    NONE = "none"
    VILLAGE = "village"
    CITY = "city"
    TOWER = "tower"
    KEEP = "keep"
    CAVE = "cave"
    RUIN = "ruin"
    HOLE = "hole"
    GRAVEYARD = "graveyard"
    CRYSTALS = "crystals"
    STONES = "stones"
    WONDER = "wonder"
    PORTAL = "portal"
    LAKE = "lake"
    RIVER = "river"


class TimeOfDay(Enum):
    """Four segments per day: morning, midday, evening, night."""

    MORNING = 0
    MIDDAY = 1
    EVENING = 2
    NIGHT = 3

    def advance(self, segments: int = 1) -> tuple["TimeOfDay", int]:
        """Advance by ``segments`` quarter-days.

        Returns a tuple ``(new_time, days_advanced)`` where
        ``days_advanced`` is the integer number of full days that
        rolled over.
        """
        if segments < 0:
            raise ValueError(f"segments must be >= 0, got {segments}")
        total = self.value + segments
        days = total // 4
        return TimeOfDay(total % 4), days


# ---------------------------------------------------------------------------
# Simple dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DungeonRef:
    """Pointer to the dungeon a hex feature exposes."""

    template: str       # e.g. "procedural:cave", "scripted:foo"
    depth: int = 1      # number of dungeon floors


@dataclass
class HexCell:
    """A single hex on the overland map."""

    coord: HexCoord
    biome: Biome
    feature: HexFeatureType = HexFeatureType.NONE
    name_key: str | None = None
    desc_key: str | None = None
    dungeon: DungeonRef | None = None


@dataclass
class Rumor:
    """A piece of intel acquired at a settlement."""

    id: str
    text_key: str
    truth: bool = True
    reveals: HexCoord | None = None


@dataclass
class Faction:
    """Stub faction definition.

    The runtime faction system lands in Phase 5 (Blackmarsh). Carried
    here so save-format reservation is in place from v1.
    """

    id: str
    name_key: str


# ---------------------------------------------------------------------------
# HexWorld
# ---------------------------------------------------------------------------


@dataclass
class HexWorld:
    """The overland state aggregate.

    Holds the per-cell map plus the player-progress sets, day clock,
    active rumours, and expedition party.
    """

    pack_id: str
    seed: int
    width: int
    height: int
    cells: dict[HexCoord, HexCell] = field(default_factory=dict)
    revealed: set[HexCoord] = field(default_factory=set)
    visited: set[HexCoord] = field(default_factory=set)
    cleared: set[HexCoord] = field(default_factory=set)
    looted: set[HexCoord] = field(default_factory=set)
    day: int = 1
    time: TimeOfDay = TimeOfDay.MORNING
    last_hub: HexCoord | None = None
    active_rumors: list[Rumor] = field(default_factory=list)
    expedition_party: list[int] = field(default_factory=list)
    biome_costs: dict[Biome, int] = field(default_factory=dict)

    # ----- cells -----

    def set_cell(self, cell: HexCell) -> None:
        self.cells[cell.coord] = cell

    def get_cell(self, c: HexCoord) -> HexCell | None:
        return self.cells.get(c)

    # ----- progress sets -----

    def reveal(self, c: HexCoord) -> None:
        self.revealed.add(c)

    def reveal_with_neighbors(self, c: HexCoord) -> None:
        """Reveal ``c`` and any neighbours that lie inside the map."""
        self.reveal(c)
        for n in neighbors(c):
            if in_bounds(n, self.width, self.height):
                self.reveal(n)

    def visit(self, c: HexCoord) -> None:
        self.reveal(c)
        self.visited.add(c)

    def is_revealed(self, c: HexCoord) -> bool:
        return c in self.revealed

    def is_visited(self, c: HexCoord) -> bool:
        return c in self.visited

    def clear_dungeon(self, c: HexCoord) -> None:
        self.cleared.add(c)

    def is_cleared(self, c: HexCoord) -> bool:
        return c in self.cleared

    # ----- clock -----

    def advance_clock(self, segments: int) -> None:
        if segments < 0:
            raise ValueError(f"segments must be >= 0, got {segments}")
        new_time, days_added = self.time.advance(segments)
        self.time = new_time
        self.day += days_added

    def advance_clock_for_cell(self, cell: HexCell) -> None:
        """Advance the clock by the cost of a step into ``cell``'s
        biome, honouring :attr:`biome_costs` override on this world."""
        # Imported lazily to avoid a circular import at module load
        # (clock.py imports DEFAULT_BIOME_COSTS from pack, which
        # imports Biome from this module).
        from nhc.hexcrawl.clock import cost_for
        self.advance_clock(cost_for(cell.biome, self.biome_costs))

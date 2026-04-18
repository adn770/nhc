"""HexCell, HexWorld, and the core hexcrawl enums.

The model is intentionally pure data: no dependency on the ECS,
rendering, or save layers. The :class:`HexWorld` aggregates per-hex
cells with the player-progress sets (revealed / visited / cleared /
looted), the day clock, the active rumour list, and the expedition
party.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from nhc.hexcrawl.coords import HexCoord, neighbors, ring


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
    # Added in M-G.1 to prepare the palette for the noise
    # generator (hills soften mountain transitions) and the
    # Blackmarsh content pack (marsh + swamp wetlands).
    HILLS = "hills"
    MARSH = "marsh"
    SWAMP = "swamp"
    # Open water / sea. A single-tile biome: one blue hex, no
    # biome-coloured dither, impassable in v1 (travel cost high
    # enough that the player routes around it).
    WATER = "water"


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


class MinorFeatureType(Enum):
    """Small discoverable features within a sub-hex."""

    NONE = "none"
    # Civilized
    FARM = "farm"
    WELL = "well"
    SHRINE = "shrine"
    SIGNPOST = "signpost"
    CAMPSITE = "campsite"
    ORCHARD = "orchard"
    # Wilderness
    CAIRN = "cairn"
    ANIMAL_DEN = "animal_den"
    HOLLOW_LOG = "hollow_log"
    MUSHROOM_RING = "mushroom_ring"
    HERB_PATCH = "herb_patch"
    BONE_PILE = "bone_pile"
    STANDING_STONE = "standing_stone"
    # Encounter-scaling (lairs)
    LAIR = "lair"
    NEST = "nest"
    BURROW = "burrow"


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
    # For cave clusters: the canonical coord (smallest (q,r) in
    # the cluster). All caves in a cluster share the same Floor 2
    # keyed by this coord. None for non-cave features or if the
    # feature hasn't been cluster-assigned yet.
    cluster_id: "HexCoord | None" = None


@dataclass
class EdgeSegment:
    """A river or path segment crossing through a hex.

    ``entry_edge`` and ``exit_edge`` are indices into
    :data:`~nhc.hexcrawl.coords.NEIGHBOR_OFFSETS` (0=N, 1=NE,
    2=SE, 3=S, 4=SW, 5=NW). ``None`` marks a source (river
    originates here) or sink (river/path terminates here).
    """

    type: str              # "river" or "path"
    entry_edge: int | None
    exit_edge: int | None
    # V2: random offset along the hex edge, [-0.4, +0.4].
    # 0.0 = midpoint. None = not yet assigned.
    entry_offset: float | None = None
    exit_offset: float | None = None


# ---------------------------------------------------------------------------
# Sub-hex flower constants and dataclasses
# ---------------------------------------------------------------------------

FLOWER_RADIUS: int = 2
"""Radius of the hex flower (5-hex diameter = radius 2)."""

_CENTER = HexCoord(0, 0)

FLOWER_COORDS: frozenset[HexCoord] = frozenset(
    ring(_CENTER, 0) + ring(_CENTER, 1) + ring(_CENTER, 2),
)
"""All 19 valid sub-hex coordinates in a hex flower (local,
centered at (0, 0))."""

# Edge-to-ring2 mapping: for each macro edge direction (0-5),
# the two ring-2 sub-hexes that sit on that edge of the flower.
# Derived from the ring() walk: edge d gets the vertex hex at
# 2 * NEIGHBOR_OFFSETS[d] plus the mid-edge hex from the
# previous ring side.
_ring2 = ring(_CENTER, FLOWER_RADIUS)
EDGE_TO_RING2: dict[int, tuple[HexCoord, HexCoord]] = {
    d: (_ring2[((d - 1) % 6) * 2 + 1], _ring2[d * 2])
    for d in range(6)
}
"""Map from macro edge index (0=N … 5=NW) to the two ring-2
sub-hexes at that flower boundary. The first element is the
mid-edge hex, the second is the vertex hex (at the edge
midpoint)."""


@dataclass
class SubHexCell:
    """A single sub-hex inside a hex flower."""

    coord: HexCoord
    biome: Biome
    elevation: float = 0.0
    minor_feature: MinorFeatureType = MinorFeatureType.NONE
    major_feature: HexFeatureType = HexFeatureType.NONE
    has_road: bool = False
    has_river: bool = False
    move_cost_hours: float = 1.0
    encounter_modifier: float = 1.0
    searched: bool = False
    tile_slot: int = 0


@dataclass
class SubHexEdgeSegment:
    """A river or road segment at sub-hex granularity.

    ``path`` is an ordered list of sub-hex coords the segment
    crosses through the flower. ``entry_macro_edge`` and
    ``exit_macro_edge`` are macro edge indices (0-5) or None
    for sources/sinks.
    """

    type: str                        # "river" or "road"
    path: list[HexCoord]
    entry_macro_edge: int | None
    exit_macro_edge: int | None
    # V2: pixel offset within the entry/exit sub-hex cell.
    entry_offset: tuple[float, float] | None = None
    exit_offset: tuple[float, float] | None = None


@dataclass
class HexFlower:
    """The 19 sub-hexes for a single macro hex."""

    parent_coord: HexCoord
    cells: dict[HexCoord, SubHexCell]
    edges: list[SubHexEdgeSegment] = field(default_factory=list)
    feature_cell: HexCoord | None = None
    fast_travel_costs: dict[tuple[int, int], float] = field(
        default_factory=dict,
    )


# ---------------------------------------------------------------------------
# Macro hex cell
# ---------------------------------------------------------------------------


@dataclass
class HexCell:
    """A single hex on the overland map."""

    coord: HexCoord
    biome: Biome
    feature: HexFeatureType = HexFeatureType.NONE
    name_key: str | None = None
    desc_key: str | None = None
    dungeon: DungeonRef | None = None
    elevation: float = 0.0
    edges: list[EdgeSegment] = field(default_factory=list)
    flower: HexFlower | None = None
    tile_slot: int = 0


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
    hour: int = 6       # 0-23; 6 = start of MORNING
    minute: int = 0     # 0-59; for 10-minute turn tracking
    last_hub: HexCoord | None = None
    active_rumors: list[Rumor] = field(default_factory=list)
    # Day on which active_rumors was last topped up by
    # Game._maybe_seed_rumors. 0 means "never seeded"; the first
    # town visit records the current day. Used for cooldown-
    # based refreshes on revisit.
    last_rumor_day: int = 0
    expedition_party: list[int] = field(default_factory=list)
    biome_costs: dict[Biome, int] = field(default_factory=dict)
    # Cave clusters: canonical coord → list of member coords.
    # Populated by _assign_cave_clusters after feature placement.
    # All caves in a cluster share a single Floor 2 dungeon.
    cave_clusters: dict[HexCoord, list[HexCoord]] = field(
        default_factory=dict,
    )
    # River coord sequences (source → sink). Each inner list is
    # one river (or branch). Populated by generate_rivers after
    # biome + elevation assignment.
    rivers: list[list[HexCoord]] = field(default_factory=list)
    # Path coord sequences. Each inner list is one path between
    # two features. Populated by generate_paths after feature
    # placement.
    paths: list[list[HexCoord]] = field(default_factory=list)
    # Sub-hex exploration state. When exploring_hex is set, the
    # player is inside a hex flower rather than on the macro map.
    exploring_hex: HexCoord | None = None
    exploring_sub_hex: HexCoord | None = None
    sub_hex_revealed: dict[HexCoord, set[HexCoord]] = field(
        default_factory=dict,
    )
    sub_hex_visited: dict[HexCoord, set[HexCoord]] = field(
        default_factory=dict,
    )
    # Direction the player last entered each macro hex from.
    # Key = macro hex coord, value = NEIGHBOR_OFFSETS index (0-5).
    last_entry_edge: dict[HexCoord, int] = field(
        default_factory=dict,
    )

    # ----- cells -----

    def set_cell(self, cell: HexCell) -> None:
        self.cells[cell.coord] = cell

    def get_cell(self, c: HexCoord) -> HexCell | None:
        return self.cells.get(c)

    # ----- progress sets -----

    def reveal(self, c: HexCoord) -> None:
        self.revealed.add(c)

    def reveal_with_neighbors(self, c: HexCoord) -> None:
        """Reveal ``c`` and any neighbours that lie inside the shape."""
        self.reveal(c)
        for n in neighbors(c):
            if n in self.cells:
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

    # ----- sub-hex exploration -----

    def enter_flower(
        self, macro_hex: HexCoord, entry_sub: HexCoord,
    ) -> None:
        """Enter a hex flower at *entry_sub*."""
        self.exploring_hex = macro_hex
        self.exploring_sub_hex = entry_sub
        self._reveal_flower_fov(macro_hex, entry_sub)
        self.sub_hex_visited.setdefault(macro_hex, set()).add(
            entry_sub,
        )

    def record_entry_edge(
        self, origin: HexCoord, target: HexCoord,
    ) -> None:
        """Record the direction the player entered *target* from."""
        from nhc.hexcrawl._rivers import direction_index
        edge = direction_index(origin, target)
        self.last_entry_edge[target] = edge

    def exit_flower(self) -> None:
        """Leave the current hex flower back to the macro map."""
        self.exploring_hex = None
        self.exploring_sub_hex = None

    def move_sub_hex(self, target: HexCoord) -> None:
        """Move within the current flower to *target*."""
        macro = self.exploring_hex
        assert macro is not None
        self.exploring_sub_hex = target
        self._reveal_flower_fov(macro, target)
        self.sub_hex_visited.setdefault(macro, set()).add(target)

    def _reveal_flower_fov(
        self, macro: HexCoord, sub: HexCoord,
    ) -> None:
        """Reveal ring-1 FOV around *sub* in the flower."""
        revealed = self.sub_hex_revealed.setdefault(macro, set())
        revealed.add(sub)
        for n in neighbors(sub):
            if n in FLOWER_COORDS:
                revealed.add(n)

    # ----- fog of war -----

    def visible_cells(self, center: HexCoord) -> set[HexCoord]:
        """Currently-in-sight hex coords around ``center``.

        With 5-mile hexes there is no extended field of view: the
        player sees only the hex they occupy. Returns ``{center}``
        when the coord is a populated cell, empty set otherwise.
        """
        if center in self.cells:
            return {center}
        return set()

    def is_in_shape(self, c: HexCoord) -> bool:
        """Shape-aware bounds check: True iff ``c`` is a populated
        cell on this map. Replaces the naive axial rectangle test
        for non-parallelogram layouts (e.g. odd-q rectangular)."""
        return c in self.cells

    def get_visible(self, c: HexCoord) -> HexCell | None:
        """Fog-respecting cell lookup.

        Returns the :class:`HexCell` at ``c`` when the coord has
        been revealed, otherwise :data:`None`. Out-of-bounds coords
        always return ``None``.
        """
        if c not in self.revealed:
            return None
        return self.cells.get(c)

    def pixel_bbox(
        self, size: float,
    ) -> tuple[float, float, float, float]:
        """Pixel extent of the overall shape.

        Returns ``(width, height, min_x, min_y)`` computed from
        populated cells so staggered / irregular layouts report
        their real on-screen extent. ``min_x``/``min_y`` are the
        raw pixel coords of the top-left-most hex centre; the
        client uses them to offset all hex positions so the map
        starts at the canvas margin. Returns four zeros for an
        empty map.
        """
        if not self.cells:
            return (0.0, 0.0, 0.0, 0.0)
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")
        sqrt3 = math.sqrt(3)
        for c in self.cells:
            x = size * 1.5 * c.q
            y = size * (sqrt3 / 2 * c.q + sqrt3 * c.r)
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y
        return max_x - min_x, max_y - min_y, min_x, min_y

    # ----- clock -----

    _SEGMENT_MAP = [
        TimeOfDay.NIGHT,    # hours 0-5
        TimeOfDay.MORNING,  # hours 6-11
        TimeOfDay.MIDDAY,   # hours 12-17
        TimeOfDay.EVENING,  # hours 18-23
    ]

    def _sync_time_from_hour(self) -> None:
        """Derive :attr:`time` from :attr:`hour`."""
        self.time = self._SEGMENT_MAP[self.hour // 6]

    def advance_clock_hours(self, hours: float) -> None:
        """Advance the clock by a fractional number of hours.

        Updates :attr:`hour`, :attr:`minute`, :attr:`time`, and
        :attr:`day`. This is the canonical clock-advance method;
        :meth:`advance_clock` delegates here.
        """
        total_minutes = self.hour * 60 + self.minute + round(hours * 60)
        self.day += total_minutes // (24 * 60)
        remaining = total_minutes % (24 * 60)
        self.hour = remaining // 60
        self.minute = remaining % 60
        self._sync_time_from_hour()

    def advance_clock(self, segments: int) -> None:
        """Advance the clock by ``segments`` quarter-days (6 h each)."""
        if segments < 0:
            raise ValueError(f"segments must be >= 0, got {segments}")
        self.advance_clock_hours(segments * 6.0)

    def advance_clock_for_cell(self, cell: HexCell) -> None:
        """Advance the clock by the cost of a step into ``cell``'s
        biome, honouring :attr:`biome_costs` override on this world."""
        # Imported lazily to avoid a circular import at module load
        # (clock.py imports DEFAULT_BIOME_COSTS from pack, which
        # imports Biome from this module).
        from nhc.hexcrawl.clock import cost_for
        self.advance_clock(cost_for(cell.biome, self.biome_costs))

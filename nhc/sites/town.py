"""Town site assembler.

See ``design/building_generator.md`` section 5.5. A town is a
set of small buildings in a grid, optionally surrounded by a
palisade, with STREET surface between buildings. Interiors mix
wood (residential / market) and stone (temple / garrison).

Four size classes tune building count, surface footprint, and
whether a palisade encloses the site:

- ``hamlet``: 3-4 buildings, no palisade, 30x22 surface.
- ``village``: 5-8 buildings, palisade, 50x30 surface.
- ``town``: 9-12 buildings, palisade, 62x36 surface.
- ``city``: 12-16 buildings, palisade, 74x42 surface.

Every size tags a subset of buildings with service roles
(``shop``, ``inn``, ``temple``, ``stable``, ``training``) and
places NPC ``EntityPlacement``s on the matching building's
ground floor: a merchant in the shop, an innkeeper + hirable
adventurer in the inn, a priest in the temple. Stable and
training are intentionally left unpopulated in v1 -- they exist
as labelled slots for future systems (mounts, XP sinks) to hook
into.

Supersedes the old single-level ``SettlementGenerator`` and
``generate_town`` helpers -- every settlement hex now routes
through this assembler regardless of size class.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from nhc.dungeon.building import Building
from nhc.dungeon.generators._stairs import (
    build_floors_with_stairs,
)
from nhc.dungeon.interior._floor import build_building_floor
from nhc.dungeon.interior.registry import ARCHETYPE_CONFIG
from nhc.dungeon.model import (
    EntityPlacement, Level, LShape, Rect, RectShape,
    RoomShape, SurfaceType, Terrain, Tile,
)
from nhc.dungeon.room_types import (
    SHOP_STOCK, TEMPLE_SERVICES_DEFAULT, TEMPLE_STOCK_DEFAULT,
)
from nhc.sites._site import (
    Enclosure, InteriorDoorLink, Site, outside_neighbour,
    paint_outer_grass_ring, paint_surface_doors,
    stamp_building_door, stamp_building_door_on_floor,
)
from nhc.sites._placement import (
    safe_floor_near, smallest_leaf_door,
)
from nhc.sites._town_layout import (
    _ClusterMember, _ClusterPlan, _cluster_pack,
)
from nhc.sites._town_streets import (
    compute_town_street_network, gates_y_for_cluster_set,
    paint_surface,
)
from nhc.sites._types import SiteTier
from nhc.hexcrawl.model import Biome, DungeonRef


# Size_class <-> SiteTier mapping. Towns historically used a 4-step
# size_class scale (hamlet / village / town / city). The unified
# tier scheme has 3 tiers in the macro range; the four sizes
# collapse to MEDIUM (hamlet) / LARGE (village) / HUGE (town /
# city). The "town" middle size remains addressable by passing
# ``size_class="town"`` directly so the existing generator pool
# stays intact; the dispatcher in M6c will use the tier mapping
# (and ``city`` becomes the default at HUGE).
_TIER_TO_SIZE_CLASS: dict[SiteTier, str] = {
    SiteTier.MEDIUM: "hamlet",
    SiteTier.LARGE: "village",
    SiteTier.HUGE: "city",
}


# ── Town tunable constants ───────────────────────────────────

TOWN_FLOOR_COUNT_RANGE = (1, 2)


# Phase 4a vegetation tunables. Per-tile probability that a
# scatter-eligible FIELD tile receives a ``tree`` feature. The
# density falls as the settlement grows so larger sites stay
# proportionally dense (more area) but visually sparser per tile.
TOWN_TREE_DENSITY: dict[str, float] = {
    "hamlet": 0.20,
    "village": 0.16,
    "town": 0.14,
    "city": 0.12,
}

# Phase 4b (M4) bush placement. Scatter pass runs after trees and
# fills remaining FIELD tiles with smaller shrubs. Density tracks
# tree density (smaller settlements feel lusher, larger sites stay
# sparser per tile).
TOWN_BUSH_DENSITY: dict[str, float] = {
    "hamlet": 0.10,
    "village": 0.09,
    "town": 0.08,
    "city": 0.07,
}

BUSH_NEIGHBOUR_BIAS_MULT = 2.5
"""Probability multiplier when an already-iterated 4-neighbour
(N, W in row-major scan) carries a bush. The bias makes bushes
"grow toward" each other into 2-3 tile rows that read as hedges
without explicit hedge logic."""


# ── Centerpiece specs (Phase 5) ──────────────────────────────


@dataclass(frozen=True)
class _CenterpieceSpec:
    """Per-size landmark on a reserved patch (Q3, Q18).

    ``feature_dim`` is the feature footprint (1 for well, 2 for
    fountain, 3 for the city 3x3 fountains). ``patch_dim`` is
    the reserved patch (3x3 for hamlet / village, 4x4 for town,
    5x5 for city). ``feature_circle`` / ``feature_square`` /
    ``feature_cross`` are the biome-driven variants.

    ``feature_cross`` is optional -- only the city spec carries
    the cross variant today (the smaller wells / 2x2 fountains
    have no plus-shaped equivalent). When unset and a biome
    routes to ``"cross"``, the dispatcher falls back to the
    circle variant.
    """

    feature_dim: int
    patch_dim: int
    feature_circle: str
    feature_square: str
    feature_cross: str | None = None


# Centerpiece patch dimensions bumped across every size class so
# the plaza around the well / fountain reads as a proper paved
# square rather than a tight collar against the feature rim:
#
#   hamlet   3 → 5   (1-tile well + 2-tile apron)
#   village  3 → 5   (1-tile well + 2-tile apron)
#   town     4 → 7   (2-tile fountain + 2-3 tile apron)
#   city     9 → 11  (3-tile fountain + 4-tile apron)
_CENTERPIECE_PER_SIZE: dict[str, _CenterpieceSpec] = {
    "hamlet": _CenterpieceSpec(1, 5, "well", "well_square"),
    "village": _CenterpieceSpec(1, 5, "well", "well_square"),
    "town": _CenterpieceSpec(2, 7, "fountain", "fountain_square"),
    "city": _CenterpieceSpec(
        3, 11,
        "fountain_large",
        "fountain_large_square",
        feature_cross="fountain_cross",
    ),
}


_BIOME_CENTERPIECE_SHAPE: dict[Biome, str] = {
    # Stone-masonry biomes -> square plinths.
    Biome.MOUNTAIN: "square",
    Biome.ICELANDS: "square",
    Biome.DRYLANDS: "square",
    Biome.SANDLANDS: "square",
    # Decay / mystical biomes get the elaborate plus shape on
    # cities (city_spec carries feature_cross). Smaller settle-
    # ments fall back to the circle variant.
    Biome.DEADLANDS: "cross",
    Biome.SWAMP: "cross",
    Biome.MARSH: "cross",
    # Lush / temperate biomes -> rounded plinths.
    Biome.FOREST: "circle",
    Biome.GREENLANDS: "circle",
    Biome.HILLS: "circle",
}
"""Q12: biome -> centerpiece shape variant. Stone-masonry biomes
 get the square variant; decay / mystical biomes get the cross
 (city only); lush biomes get the rounded variant. Default
 ``"circle"`` covers ``biome=None`` and any unmapped biome."""


def _centerpiece_feature_tag(
    spec: _CenterpieceSpec, biome: Biome | None,
) -> str:
    if biome is None:
        return spec.feature_circle
    shape = _BIOME_CENTERPIECE_SHAPE.get(biome, "circle")
    if shape == "square":
        return spec.feature_square
    if shape == "cross" and spec.feature_cross is not None:
        return spec.feature_cross
    return spec.feature_circle

TOWN_WOOD_BUILDING_PROBABILITY = 0.65    # rest are stone
TOWN_DESCENT_PROBABILITY = 0.08
TOWN_DESCENT_TEMPLATE = "procedural:crypt"

TOWN_PALISADE_PADDING = 3                # tiles beyond bbox
TOWN_GATE_COUNT_RANGE = (1, 2)
TOWN_GATE_LENGTH_TILES = 2

# Service role vocabulary. The first three roles own NPCs that
# ``_spawn_level_entities`` pulls into the ECS world on interior
# entry; stable and training stay empty (reserved slots).
SERVICE_ROLES_WITH_NPCS: tuple[str, ...] = ("shop", "inn", "temple")
SERVICE_ROLES_RESERVED: tuple[str, ...] = ("stable", "training")
SERVICE_ROLES: tuple[str, ...] = (
    SERVICE_ROLES_WITH_NPCS + SERVICE_ROLES_RESERVED
)


@dataclass(frozen=True)
class _TownSizeConfig:
    """Per-size layout tunables.

    ``palisade_outer_width / palisade_outer_height`` declare the
    outer dimensions of the palisade rectangle (or, for non-
    palisade sizes, the buildable area that occupies the same
    role). The actual ``Level`` surface allocated by the assembler
    is ``palisade_outer + 2`` so a 1-tile VOID margin surrounds
    every renderable element on the canvas — see
    ``design/level_surface_layout.md``.
    """

    building_count_range: tuple[int, int]
    palisade_outer_width: int
    palisade_outer_height: int
    has_palisade: bool
    # Enclosure stone vs wood — ``"palisade"`` (default) renders
    # wood logs with a Wood family stroke; ``"fortification"``
    # renders stone walls with a Stone family stroke (the keep
    # treatment). Cities use fortification to read as the most
    # urban / urbanised tier.
    enclosure_kind: str = "palisade"
    # Pave every walkable tile inside the enclosure (FIELD / GARDEN
    # → STREET) so the city renders as a uniformly paved courtyard
    # with buildings packed in. False for hamlet / village / town
    # which keep open grass + garden patches between routed streets.
    paved_courtyard: bool = False
    # Width of the grass ring between the (palisade) outer rect
    # and the canvas edge. ``1`` for hamlet (the existing 1-tile
    # buffer that previously rendered as VOID — now grass). ``2``
    # for the palisade-bearing tiers (village / town / city) so
    # the wall sits on a 2-tile-deep grass apron with scattered
    # vegetation. The palisade rect insets by ``ring`` from the
    # canvas edge; surface dims stay at
    # ``palisade_outer + 2`` so content packs tighter rather than
    # the canvas growing.
    grass_ring_width: int = 1

    @property
    def surface_width(self) -> int:
        return self.palisade_outer_width + 2

    @property
    def surface_height(self) -> int:
        return self.palisade_outer_height + 2


@dataclass(frozen=True)
class _BiomeOverrides:
    """Biome-driven tweaks applied on top of the size-class config.

    ``wall_material`` / ``interior_floor`` force every building to
    the given material when set; ``None`` falls through to the
    default wood/brick/stone roll. ``suppress_palisade`` flips the
    size-class palisade off regardless of has_palisade. ``skew_small``
    clamps the building-count roll to the lower half of the range.
    ``ambient`` overrides ``surface.metadata.ambient`` when set.
    """

    wall_material: str | None = None
    interior_floor: str | None = None
    suppress_palisade: bool = False
    skew_small: bool = False
    ambient: str | None = None


_BIOME_OVERRIDES: dict[Biome, _BiomeOverrides] = {
    Biome.MOUNTAIN: _BiomeOverrides(
        wall_material="stone", interior_floor="stone",
        suppress_palisade=True, skew_small=True,
    ),
    Biome.DRYLANDS: _BiomeOverrides(
        wall_material="adobe", interior_floor="earth",
    ),
    Biome.MARSH: _BiomeOverrides(
        wall_material="wood", interior_floor="wood",
        ambient="stilted",
    ),
}


def _biome_overrides(biome: Biome | None) -> _BiomeOverrides:
    """Return the override bundle for ``biome`` (or empty defaults)."""
    if biome is None:
        return _BiomeOverrides()
    return _BIOME_OVERRIDES.get(biome, _BiomeOverrides())


_SIZE_CLASSES: dict[str, _TownSizeConfig] = {
    # ``palisade_outer_*`` carries the outer dim of the palisade
    # rect (or the buildable area for non-palisade hamlets);
    # numeric values are the C3-tuned sizes that previously lived
    # in ``surface_width / surface_height``. The actual surface
    # ``Level`` is ``palisade_outer + 2`` so the 1-tile VOID
    # margin contract holds — see
    # ``design/level_surface_layout.md``.
    # Hamlet surface tightened from 56 × 52 → 56 × 40 so the
    # 3-4 buildings + their immediate FIELD periphery read as a
    # cozy isolated cluster rather than two cottages lost in a
    # forest. Width stays at 56 to leave the cluster packer
    # enough horizontal slack for two side-by-side clusters of
    # the larger temple / inn-sized buildings (16×16 footprints
    # still appear at the hamlet tier); height drops 12 tiles
    # to crop the empty FIELD halo above and below the buildings.
    "hamlet": _TownSizeConfig(
        building_count_range=(3, 4),
        palisade_outer_width=56,
        palisade_outer_height=40,
        has_palisade=False,
    ),
    "village": _TownSizeConfig(
        building_count_range=(5, 7),
        palisade_outer_width=72,
        palisade_outer_height=58,
        has_palisade=True,
        grass_ring_width=2,
    ),
    "town": _TownSizeConfig(
        building_count_range=(8, 10),
        palisade_outer_width=88,
        palisade_outer_height=72,
        has_palisade=True,
        grass_ring_width=2,
    ),
    # City building count bumped progressively from (10, 13) →
    # (14, 18) → (18, 22) → (40, 48) so the tier reads as a dense
    # urban settlement, clearly distinct from the town predecessor.
    # The street network branches per cluster anchor, so more
    # buildings + more clusters naturally pull in more side streets
    # without growing the spine logic. Surface dims stay at 104 × 86
    # — the goal is "more packed", not "bigger area". Note: the
    # cluster placer drops a few clusters per seed when the
    # rejection sampling exhausts; the actual ``len(site.buildings)``
    # observed across 50 seeds with the current packing settings
    # falls in [34, 46], roughly doubling the previous (18, 22).
    "city": _TownSizeConfig(
        building_count_range=(40, 48),
        palisade_outer_width=104,
        palisade_outer_height=86,
        has_palisade=True,
        enclosure_kind="fortification",
        paved_courtyard=True,
        grass_ring_width=2,
    ),
}


# Per-size street material (encoded as a ``(family, style,
# sub_pattern)`` int triple). Mirrors ``MaterialFamily.Stone = 3``
# and the style / sub-pattern constants in
# ``nhc/rendering/emit/materials.py`` (``STONE_FIELDSTONE = 4``,
# ``STONE_COBBLESTONE = 0`` + ``RUBBLE = 2``,
# ``STONE_FLAGSTONE = 2``, ``STONE_BRICK = 1`` +
# ``FLEMISH_BOND = 2``). Settlements stamp this onto
# ``surface.metadata.street_material`` so the v5 emit pipeline
# overrides the ``paved.*`` PaintOp material per size class. The
# urbanisation gradient runs hamlet → city: rough natural fieldstone
# at the smallest tier, refined bonded brick at the largest.
_STREET_MATERIAL_BY_SIZE: dict[str, tuple[int, int, int]] = {
    "hamlet": (3, 4, 0),    # Stone / FieldStone
    "village": (3, 0, 2),   # Stone / Cobblestone / Rubble
    "town": (3, 2, 0),      # Stone / Flagstone
    "city": (3, 2, 0),      # Stone / Flagstone (paired with
    # the Ashlar Staggered open pavement for a uniformly stone
    # urban look — fortified, paved, dressed-stone city).
}


# Per-size open-courtyard pavement material — only the city tier
# stamps ``SurfaceType.PAVEMENT`` (the post-pass that paves every
# walkable tile outside the routed FlemishBond streets), so this
# table is single-entry. Encoded as ``(family, style, sub_pattern)``
# matching the constants in ``nhc/rendering/emit/materials.py``.
_PAVEMENT_MATERIAL_BY_SIZE: dict[str, tuple[int, int, int]] = {
    "city": (3, 8, 1),      # Stone / Ashlar / Staggered Joint
}


def _palisade_outer_rect(config: _TownSizeConfig) -> Rect:
    """Return the palisade outer rect in surface coords.

    The rect insets by ``config.grass_ring_width`` from each
    canvas edge so a grass apron sits between the wall and the
    edge. Surface dims stay at ``palisade_outer + 2``; for a
    ``ring=2`` settlement the actual palisade rect dims shrink
    by 2 in each axis (the wall packs tighter rather than the
    canvas growing).
    """
    ring = config.grass_ring_width
    inset = 2 * (ring - 1)
    return Rect(
        ring, ring,
        config.palisade_outer_width - inset,
        config.palisade_outer_height - inset,
    )


def _buildable_bounds(
    config: _TownSizeConfig, has_palisade: bool,
) -> tuple[int, int, int, int]:
    """Return ``(min_x, min_y, max_x, max_y)`` for cluster
    placement in surface coords. ``max_*`` is exclusive — same
    shape ``_place_clusters`` already consumes internally.

    For palisade-bearing sites the buildable interior is inset
    from the palisade outer rect by :data:`TOWN_PALISADE_PADDING`
    on every side. For non-palisade sites the buildable area is
    the full palisade-outer-sized rect: clusters spread within
    the grass-ring margin without a wall to step around.
    """
    pal = _palisade_outer_rect(config)
    if has_palisade:
        pad = TOWN_PALISADE_PADDING
        return (
            pal.x + pad, pal.y + pad,
            pal.x2 - pad, pal.y2 - pad,
        )
    return (pal.x, pal.y, pal.x2, pal.y2)


def assemble_town(
    site_id: str,
    rng: random.Random,
    size_class: str | None = None,
    biome: Biome | None = None,
    *, tier: SiteTier | None = None,
) -> Site:
    """Assemble a town site.

    ``size_class`` must be one of ``hamlet``, ``village``,
    ``town`` or ``city``. ``None`` (the default) falls back to
    ``tier`` if it is set, otherwise ``"village"``.

    ``tier`` is the unified ``Game.enter_site`` dispatcher
    parameter (M6b). MEDIUM / LARGE / HUGE map to hamlet /
    village / city respectively; the in-between ``town`` size is
    still reachable via ``size_class="town"``. Passing both
    ``size_class`` and ``tier`` is fine; ``size_class`` wins.

    ``biome`` is an optional :class:`Biome` that lets the
    assembler tweak its defaults via :data:`_BIOME_OVERRIDES`
    without growing a new feature type. Mountain settlements get
    stone walls, no palisade, and skewed-small building counts;
    drylands towns land adobe walls over packed-earth floors;
    marsh towns switch to stilted wood with a ``"stilted"``
    surface ambient marker the frontend can raise a tile for.
    All other biomes fall through to the unmodified defaults.
    """
    if size_class is None:
        if tier is not None:
            if tier not in _TIER_TO_SIZE_CLASS:
                raise ValueError(
                    f"town only supports MEDIUM / LARGE / HUGE "
                    f"tiers; got {tier!r}",
                )
            size_class = _TIER_TO_SIZE_CLASS[tier]
        else:
            size_class = "village"
    if size_class not in _SIZE_CLASSES:
        raise ValueError(f"unknown town size_class: {size_class!r}")
    config = _SIZE_CLASSES[size_class]
    overrides = _biome_overrides(biome)

    if overrides.skew_small:
        lo, hi = config.building_count_range
        # Clamp to the lower half so small-biome sites never push
        # to the top of the band. Guarantees at least one building.
        skewed_hi = max(lo, (lo + hi) // 2)
        n_buildings = rng.randint(lo, skewed_hi)
    else:
        n_buildings = rng.randint(*config.building_count_range)

    # Assign the role of each building BEFORE placement so the
    # cluster packer can draw a per-role size. The returned list
    # is role-by-slot, one string per building, with every service
    # role covered first and the rest filled with "residential".
    roles = _roll_role_slots(rng, n_buildings)
    sizes = [_draw_size_for_role(role, rng) for role in roles]
    has_palisade = (
        config.has_palisade and not overrides.suppress_palisade
    )
    if has_palisade:
        gate_sides = ["west", "east"]
        rng.shuffle(gate_sides)
    else:
        gate_sides = []
    bounds = _buildable_bounds(config, has_palisade)
    # Phase 5 two-pass placement: probe-pass packer determines a
    # rough cluster bbox set; we compute the centerpiece patch
    # origin and reserve it as a forbidden_rect for the final
    # cluster pack so clusters arrange around the landmark.
    probe_plans = _cluster_pack(
        roles, sizes, config, size_class, rng, bounds=bounds,
    )
    cp_spec = _CENTERPIECE_PER_SIZE.get(size_class)
    cp_origin: tuple[int, int] | None = None
    forbidden_rects: list[Rect] = []
    if cp_spec is not None and probe_plans:
        cp_origin = _compute_centerpiece_origin(
            probe_plans, gate_sides, cp_spec, bounds, rng,
        )
        if cp_origin is not None:
            ox, oy = cp_origin
            forbidden_rects.append(
                Rect(ox, oy, cp_spec.patch_dim, cp_spec.patch_dim),
            )

    cluster_plans = _cluster_pack(
        roles, sizes, config, size_class, rng,
        forbidden_rects=forbidden_rects, bounds=bounds,
    )
    buildings = _place_buildings(
        site_id, rng, roles, sizes, cluster_plans,
        overrides=overrides,
    )
    # Pair each placed building with its original role by index
    # (the cluster packer can drop members at the dense city
    # tier, so ``buildings`` is shorter than ``roles`` — a
    # positional ``zip`` pairs the wrong role with the wrong
    # building, giving stables the residential tag and vice
    # versa). Building ids encode the original role index as the
    # ``_b{i}`` suffix.
    role_assignments: dict[str, str] = {}
    for b in buildings:
        original_index = int(b.id.rsplit("_b", 1)[1])
        role = roles[original_index]
        if role == "residential":
            continue
        role_assignments[b.id] = role
        b.floors[0].rooms[0].tags.append(role)

    # Mountain lodges read best without a palisade; everything else
    # inherits the size-class default.
    if has_palisade:
        enclosure = _build_palisade(
            _palisade_outer_rect(config), cluster_plans, rng,
            sides=gate_sides,
            kind=config.enclosure_kind,
        )
    else:
        enclosure = None
    cp_rect = forbidden_rects[0] if forbidden_rects else None
    surface = _build_town_surface(
        f"{site_id}_surface", buildings, enclosure,
        cluster_plans, size_class, config,
        centerpiece_rect=cp_rect,
        open_bounds=bounds,
    )
    if cp_origin is not None and cp_spec is not None:
        _stamp_centerpiece(surface, cp_origin, cp_spec, biome)
    if overrides.ambient is not None:
        surface.metadata.ambient = overrides.ambient

    # Phase 3: door placement runs AFTER the surface paints so the
    # candidate's outside-neighbour `surface_type` is meaningful.
    # This re-orders the legacy roles -> buildings -> doors flow to
    # roles -> buildings -> surface -> doors.
    combined_footprints: set[tuple[int, int]] = set()
    for b in buildings:
        combined_footprints |= b.base_shape.floor_tiles(b.base_rect)
    door_map: dict[tuple[int, int], tuple[str, int, int]] = {}
    for plan in cluster_plans:
        for member in plan.members:
            building = next(
                (
                    b for b in buildings
                    if b.id.endswith(f"_b{member.index}")
                ),
                None,
            )
            if building is None:
                continue
            own = building.base_shape.floor_tiles(
                building.base_rect,
            )
            others = combined_footprints - own
            door_xy = _place_entry_door(
                building, rng, blocked=others,
                surface=surface, plan=plan, member=member,
            )
            if door_xy is not None:
                neighbour = outside_neighbour(
                    building, *door_xy,
                )
                if neighbour is not None:
                    door_map[neighbour] = (
                        building.id, door_xy[0], door_xy[1],
                    )
            building.validate()

    site = Site(
        id=site_id,
        kind="town",
        buildings=buildings,
        surface=surface,
        enclosure=enclosure,
    )
    site.building_doors.update(door_map)
    site.cluster_plans = cluster_plans
    paint_surface_doors(site, SurfaceType.STREET)
    if config.paved_courtyard:
        # Cities pave their enclosure interior — every remaining
        # GARDEN / FIELD tile inside the palisade rect becomes
        # PAVEMENT so the courtyard renders as one paved surface
        # (Ashlar Staggered via ``pavement_material``). Restricted
        # to the palisade interior so the FIELD tiles in the
        # outer grass ring (trees / bushes outside the wall)
        # survive. Runs BEFORE the vegetation scatter so the
        # subsequent pass sees inner-courtyard tiles as PAVEMENT
        # (and skips them) while the outer ring stays FIELD and
        # accepts the canopy.
        _pave_courtyard_post_pass(surface, _palisade_outer_rect(config))
    # Vegetation scatter walks every FIELD tile. After the
    # ``_paint_outer_grass_ring`` step, the outer grass apron is
    # FIELD too, so this pass also seeds trees / bushes outside
    # the palisade — visible on every settlement size. Cities run
    # the pave-courtyard pass above first, so only the outer ring
    # remains FIELD when scatter walks the surface.
    _scatter_town_vegetation(
        site, cluster_plans, size_class, rng,
    )
    _scatter_town_bushes(
        site, cluster_plans, size_class, rng,
    )
    _place_service_npcs(buildings, role_assignments, rng)
    _place_surface_adventurers(site, role_assignments, rng)
    _lock_shop_doors(buildings, role_assignments, rng)
    _place_surface_villagers(site, size_class, rng)
    _connect_cross_building_doors(site, cluster_plans)
    return site


def _roll_role_slots(
    rng: random.Random, n_buildings: int,
) -> list[str]:
    """Decide which role each building slot carries.

    The three NPC-bearing service roles (``shop``, ``inn``,
    ``temple``) are filled first, followed by the reserved
    ``stable`` / ``training`` slots if there is room. Remaining
    slots are plain ``"residential"``. The whole list is then
    shuffled so the placement order doesn't encode the role.
    """
    role_order = list(SERVICE_ROLES_WITH_NPCS) + list(
        SERVICE_ROLES_RESERVED,
    )
    if n_buildings <= len(role_order):
        slots = role_order[:n_buildings]
    else:
        slots = role_order + [
            "residential"
        ] * (n_buildings - len(role_order))
    rng.shuffle(slots)
    return slots


def _draw_size_for_role(
    role: str, rng: random.Random,
) -> tuple[int, int]:
    """Draw ``(width, height)`` from the role's size_range."""
    spec = ARCHETYPE_CONFIG[role]
    w = rng.randint(*spec.size_range)
    h = rng.randint(*spec.size_range)
    return (w, h)


def _place_buildings(
    site_id: str, rng: random.Random,
    roles: list[str], sizes: list[tuple[int, int]],
    cluster_plans: list[_ClusterPlan],
    overrides: _BiomeOverrides | None = None,
) -> list[Building]:
    """Materialise :class:`Building`s from the cluster packer's
    output.

    ``roles`` and ``sizes`` are parallel lists, one entry per
    building. ``cluster_plans`` carries the placed cluster bboxes
    + per-member rects produced by
    :func:`nhc.sites._town_layout._cluster_pack`. Buildings are
    indexed by their original input position so service-role
    assignment, descent rolls and stable building ids stay in
    register with the role list.
    """
    overrides = overrides or _BiomeOverrides()
    placements_by_index: dict[int, Rect] = {}
    for plan in cluster_plans:
        for member in plan.members:
            placements_by_index[member.index] = member.rect
    buildings: list[Building] = []
    for i, role in enumerate(roles):
        rect = placements_by_index.get(i)
        if rect is None:
            # Cluster packer dropped this member (extremely rare);
            # skip so the rest of the site still assembles.
            continue
        shape = _pick_shape_for_role(rng, role)
        n_floors = rng.randint(*TOWN_FLOOR_COUNT_RANGE)
        if overrides.interior_floor is not None:
            interior = overrides.interior_floor
        else:
            is_wood = rng.random() < TOWN_WOOD_BUILDING_PROBABILITY
            interior = "wood" if is_wood else "stone"
        descent: DungeonRef | None = None
        if rng.random() < TOWN_DESCENT_PROBABILITY:
            descent = DungeonRef(template=TOWN_DESCENT_TEMPLATE)
        building = _build_town_building(
            f"{site_id}_b{i}", shape, rect,
            n_floors, descent, interior, rng,
            archetype=role,
            wall_override=overrides.wall_material,
        )
        buildings.append(building)
    return buildings


def _pick_shape_for_role(
    rng: random.Random, role: str,
) -> RoomShape:
    """Pick a RoomShape from the role's ``shape_pool``.

    Maps registry shape keys (``"rect"``, ``"l"``) to concrete
    shape instances. Unsupported keys (``"circle"``, ``"octagon"``)
    never appear in town archetypes today, so we raise on them
    rather than silently degrading — loud failure per the design
    doc's KeyError policy.
    """
    spec = ARCHETYPE_CONFIG[role]
    key = rng.choice(spec.shape_pool)
    if key == "rect":
        return RectShape()
    if key == "l":
        return LShape(corner=rng.choice(LShape._VALID_CORNERS))
    raise ValueError(
        f"unsupported shape key {key!r} for town role {role!r}"
    )


def _build_town_building(
    building_id: str, base_shape: RoomShape, base_rect: Rect,
    n_floors: int, descent: DungeonRef | None,
    interior: str, rng: random.Random,
    archetype: str = "residential",
    wall_override: str | None = None,
) -> Building:
    floors, stair_links = build_floors_with_stairs(
        building_id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        n_floors=n_floors,
        descent=descent,
        rng=rng,
        build_floor_fn=lambda idx, n, req: _build_town_floor(
            building_id, idx, base_shape, base_rect, n, rng,
            archetype=archetype,
            required_walkable=req,
        ),
    )
    for f in floors:
        f.interior_floor = interior
    if wall_override is not None:
        wall_material = wall_override
    else:
        wall_material = "brick" if interior == "wood" else "stone"
    building = Building(
        id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        floors=floors,
        descent=descent,
        wall_material=wall_material,
        interior_floor=interior,
        interior_wall_material=(
            ARCHETYPE_CONFIG[archetype].interior_wall_material
        ),
    )
    building.stair_links = stair_links
    return building


def _build_town_floor(
    building_id: str, floor_idx: int,
    base_shape: RoomShape, base_rect: Rect,
    n_floors: int, rng: random.Random,
    archetype: str = "residential",
    required_walkable: frozenset[tuple[int, int]] = frozenset(),
) -> Level:
    return build_building_floor(
        building_id=building_id,
        floor_idx=floor_idx,
        base_shape=base_shape,
        base_rect=base_rect,
        n_floors=n_floors,
        rng=rng,
        archetype=archetype,
        tags=["town_interior"],
        required_walkable=required_walkable,
    )


_DOOR_PRIORITY_DEFAULT: tuple[SurfaceType, ...] = (
    SurfaceType.STREET, SurfaceType.GARDEN, SurfaceType.FIELD,
)
_DOOR_PRIORITY_GARDEN_FIRST: tuple[SurfaceType, ...] = (
    SurfaceType.GARDEN, SurfaceType.STREET, SurfaceType.FIELD,
)


def _door_priority(
    plan: "_ClusterPlan | None",
    member: "_ClusterMember | None",
) -> tuple[SurfaceType, ...]:
    """Per-archetype priority for door surface_type selection (Q15).

    L-block elbow + courtyard east/west buildings prefer GARDEN;
    every other archetype prefers STREET. ``plan`` and ``member``
    are ``None`` for non-cluster contexts (returns the default
    STREET-first priority).
    """
    if plan is None or member is None:
        return _DOOR_PRIORITY_DEFAULT
    if plan.kind == "l_block":
        # `_layout_l_block` puts the elbow at members[0].
        if plan.members and plan.members[0].index == member.index:
            return _DOOR_PRIORITY_GARDEN_FIRST
        return _DOOR_PRIORITY_DEFAULT
    if plan.kind == "courtyard":
        # `_layout_courtyard` returns members in N, E, S, W order.
        # N (idx 0) and S (idx 2) face STREET; E (idx 1) and W
        # (idx 3) face GARDEN.
        if not plan.members:
            return _DOOR_PRIORITY_DEFAULT
        position = next(
            (
                i for i, m in enumerate(plan.members)
                if m.index == member.index
            ),
            None,
        )
        if position in (1, 3):
            return _DOOR_PRIORITY_GARDEN_FIRST
        return _DOOR_PRIORITY_DEFAULT
    return _DOOR_PRIORITY_DEFAULT


def _place_entry_door(
    building: Building, rng: random.Random,
    blocked: set[tuple[int, int]] | None = None,
    surface: Level | None = None,
    plan: "_ClusterPlan | None" = None,
    member: "_ClusterMember | None" = None,
) -> tuple[int, int] | None:
    """Pick a perimeter tile to stamp as the entry door.

    ``blocked`` carries the combined footprints of every OTHER
    building in the site. ``surface`` and ``plan`` enable the
    Phase 3 street bias: candidates are bucketed by their outside-
    neighbour's surface_type, and the first non-empty bucket wins
    (priority order from :func:`_door_priority` -- STREET-first
    by default, GARDEN-first for L-block elbow + courtyard side
    buildings per Q15). Within a bucket the helper picks the tile
    closest to the cluster centroid so doors face into the network
    rather than off the back of the cluster.
    """
    blocked = blocked or set()
    ground = building.ground
    perim = building.shared_perimeter()
    priority = _door_priority(plan, member)
    bucketed: dict[
        SurfaceType | None, list[tuple[int, int, tuple[int, int]]],
    ] = {st: [] for st in priority}
    bucketed[None] = []  # surface_type unset / outside palisade
    centroid: tuple[int, int] = (
        building.base_rect.x + building.base_rect.width // 2,
        building.base_rect.y + building.base_rect.height // 2,
    )
    if plan is not None and plan.members:
        cx = sum(
            m.rect.x + m.rect.width // 2 for m in plan.members
        ) // len(plan.members)
        cy = sum(
            m.rect.y + m.rect.height // 2 for m in plan.members
        ) // len(plan.members)
        centroid = (cx, cy)
    for (px, py) in perim:
        tile = ground.tiles[py][px]
        if tile.feature is not None:
            continue
        has_wall = False
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = px + dx, py + dy
            if not ground.in_bounds(nx, ny):
                continue
            if ground.tiles[ny][nx].terrain == Terrain.WALL:
                has_wall = True
                break
        if not has_wall:
            continue
        nb = outside_neighbour(building, px, py)
        if nb is None or nb in blocked:
            continue
        if surface is not None and surface.in_bounds(*nb):
            nb_tile = surface.tiles[nb[1]][nb[0]]
            nb_st = nb_tile.surface_type
            # Doors must face a walkable surface tile -- FLOOR for
            # STREET / FIELD, GRASS for the Phase 3a GARDEN flip.
            if nb_tile.terrain not in (Terrain.FLOOR, Terrain.GRASS):
                continue
        else:
            nb_st = None
        dist = (
            abs(nb[0] - centroid[0]) + abs(nb[1] - centroid[1])
        )
        bucketed.setdefault(nb_st, []).append((dist, px, (px, py)))

    chosen: tuple[int, int] | None = None
    for st in priority:
        bucket = bucketed.get(st)
        if not bucket:
            continue
        bucket.sort()
        chosen = bucket[0][2]
        break
    if chosen is None:
        # Fall back to any unprioritised bucket.
        for st, bucket in bucketed.items():
            if not bucket:
                continue
            bucket.sort()
            chosen = bucket[0][2]
            break
    if chosen is None:
        return None
    dx, dy = chosen
    stamp_building_door(building, dx, dy)
    return (dx, dy)


def _scatter_town_vegetation(
    site: Site,
    cluster_plans: list[_ClusterPlan],
    size_class: str,
    rng: random.Random,
) -> None:
    """Scatter ``tree`` features across FIELD periphery tiles.

    Per-tile probability is :data:`TOWN_TREE_DENSITY` for the
    given size class. Skips tiles already carrying a feature,
    tiles 4-adjacent to a building footprint (Q16 -- the medium
    canopy radius would otherwise overlap a building roof in the
    SVG render), tiles in the door 4-ring and tiles inside any
    courtyard cluster bbox (Q7 -- courtyards stay shrub-free so
    they read as paved working yards).
    """
    density = TOWN_TREE_DENSITY.get(size_class, 0.0)
    if density <= 0.0:
        return
    surface = site.surface
    footprints: set[tuple[int, int]] = set()
    for b in site.buildings:
        footprints |= b.base_shape.floor_tiles(b.base_rect)
    door_ring: set[tuple[int, int]] = set()
    for sx, sy in site.building_doors:
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            door_ring.add((sx + dx, sy + dy))
    courtyard_bboxes = [
        p.bbox for p in cluster_plans if p.kind == "courtyard"
    ]

    def _inside_courtyard(x: int, y: int) -> bool:
        for bbox in courtyard_bboxes:
            if (bbox.x <= x < bbox.x2
                    and bbox.y <= y < bbox.y2):
                return True
        return False

    for y, row in enumerate(surface.tiles):
        for x, tile in enumerate(row):
            # Phase 3b: FIELD tiles render on Terrain.GRASS so the
            # theme grass tint paints under the scattered-stone
            # overlay. Restrict tree scatter to the GRASS-tagged
            # FIELD pool to make the "trees grow on grass" intent
            # explicit (matches today's behavior since every
            # FIELD tile now carries GRASS terrain).
            if tile.terrain is not Terrain.GRASS:
                continue
            if tile.surface_type != SurfaceType.FIELD:
                continue
            if tile.feature is not None:
                continue
            if (x, y) in door_ring:
                continue
            if _inside_courtyard(x, y):
                continue
            blocked = False
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                if (x + dx, y + dy) in footprints:
                    blocked = True
                    break
            if blocked:
                continue
            if rng.random() < density:
                tile.feature = "tree"


def _scatter_town_bushes(
    site: Site,
    cluster_plans: list[_ClusterPlan],
    size_class: str,
    rng: random.Random,
) -> None:
    """Scatter ``bush`` features across remaining FIELD tiles
    after the tree pass.

    Per-tile probability is :data:`TOWN_BUSH_DENSITY` for the
    given size class, multiplied by
    :data:`BUSH_NEIGHBOUR_BIAS_MULT` when an already-iterated
    4-neighbour (N, W in row-major scan) already carries a bush.
    The bias makes bushes "grow toward" each other into 2-3 tile
    rows that read as hedges without explicit hedge logic.

    Skips tiles already carrying a feature (so trees claimed in
    the previous pass stay), tiles in the door 4-ring and tiles
    inside any courtyard cluster bbox (Q7). Bushes ARE allowed
    4-adjacent to building footprints -- the canopy stays inside
    its own tile so it never bleeds onto a roof (M3 escape hatch).
    """
    density = TOWN_BUSH_DENSITY.get(size_class, 0.0)
    if density <= 0.0:
        return
    surface = site.surface
    door_ring: set[tuple[int, int]] = set()
    for sx, sy in site.building_doors:
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            door_ring.add((sx + dx, sy + dy))
    courtyard_bboxes = [
        p.bbox for p in cluster_plans if p.kind == "courtyard"
    ]

    def _inside_courtyard(x: int, y: int) -> bool:
        for bbox in courtyard_bboxes:
            if (bbox.x <= x < bbox.x2
                    and bbox.y <= y < bbox.y2):
                return True
        return False

    bush_set: set[tuple[int, int]] = set()
    for y, row in enumerate(surface.tiles):
        for x, tile in enumerate(row):
            if tile.terrain is not Terrain.GRASS:
                continue
            if tile.surface_type != SurfaceType.FIELD:
                continue
            if tile.feature is not None:
                continue
            if (x, y) in door_ring:
                continue
            if _inside_courtyard(x, y):
                continue
            has_bush_nb = (
                (x - 1, y) in bush_set
                or (x, y - 1) in bush_set
            )
            prob = (
                density * BUSH_NEIGHBOUR_BIAS_MULT
                if has_bush_nb
                else density
            )
            if rng.random() < prob:
                tile.feature = "bush"
                bush_set.add((x, y))


def _build_palisade(
    palisade_outer: Rect,
    cluster_plans: list[_ClusterPlan],
    rng: random.Random,
    sides: list[str] | None = None,
    kind: str = "palisade",
) -> Enclosure:
    """Wrap the buildable interior in a palisade of fixed size
    and place gates at the cluster-bbox-set y-midpoint (Q14).

    ``palisade_outer`` is the predetermined outer rect (surface
    coords) — derived from :class:`_TownSizeConfig` rather than
    shrink-wrapped from building bboxes. This means a city
    palisade has the same outer dimensions across seeds,
    matching the 1-tile VOID margin contract documented in
    ``design/level_surface_layout.md``.

    ``sides`` lets the caller pre-shuffle the gate side order so
    the centerpiece's nudge direction (Phase 5) and the actual
    gate placement agree on the dominant gate. Pass ``None`` to
    have the helper shuffle internally; callers that don't run
    the Phase 5 probe should leave it ``None``.
    """
    min_x, min_y = palisade_outer.x, palisade_outer.y
    max_x = palisade_outer.x2
    max_y = palisade_outer.y2
    polygon = [
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
    ]
    gate_count = rng.randint(*TOWN_GATE_COUNT_RANGE)
    gate_ys = gates_y_for_cluster_set(cluster_plans, gate_count)
    if sides is None:
        sides = ["west", "east"]
        rng.shuffle(sides)
    gates: list[tuple[int, int, int]] = []
    for i, gy in enumerate(gate_ys):
        side = sides[i % len(sides)]
        gx = min_x if side == "west" else max_x
        gates.append((gx, gy, TOWN_GATE_LENGTH_TILES))
    return Enclosure(
        kind=kind, polygon=polygon, gates=gates,
    )


def _compute_centerpiece_origin(
    probe_plans: list[_ClusterPlan],
    gate_sides: list[str],
    spec: _CenterpieceSpec,
    bounds: tuple[int, int, int, int],
    rng: random.Random,
) -> tuple[int, int] | None:
    """Pick the centerpiece patch's top-left tile (Q10).

    Centroid of the probe-pass cluster bbox set, nudged 1-2 tiles
    along the centroid -> dominant-gate vector. Snaps to a tile
    that fits the patch dim and stays inside ``bounds``
    (``(min_x, min_y, max_x, max_y)`` in surface coords, ``max_*``
    exclusive) so the patch lands within the buildable interior
    on palisade-bearing sites and within the 1-tile VOID margin
    on hamlets."""
    if not probe_plans:
        return None
    xs_lo = min(p.bbox.x for p in probe_plans)
    ys_lo = min(p.bbox.y for p in probe_plans)
    xs_hi = max(p.bbox.x2 for p in probe_plans)
    ys_hi = max(p.bbox.y2 for p in probe_plans)
    cx = (xs_lo + xs_hi) // 2
    cy = (ys_lo + ys_hi) // 2
    if gate_sides:
        nudge = rng.randint(1, 2)
        if gate_sides[0] == "east":
            cx += nudge
        elif gate_sides[0] == "west":
            cx -= nudge
    half = spec.patch_dim // 2
    ox = cx - half
    oy = cy - half
    min_x, min_y, max_x, max_y = bounds
    ox = max(min_x, min(max_x - spec.patch_dim, ox))
    oy = max(min_y, min(max_y - spec.patch_dim, oy))
    return (ox, oy)


def _stamp_centerpiece(
    surface: Level,
    patch_origin: tuple[int, int],
    spec: _CenterpieceSpec,
    biome: Biome | None,
) -> None:
    """Stamp the centerpiece patch (cobblestone-paved plaza) and
    the feature tag (well / well_square / fountain /
    fountain_square).

    The patch carries ``SurfaceType.STREET`` -- same cobblestone
    pattern as the surrounding streets. The fountain or well
    itself is the visual centerpiece; no separate floor pattern
    is needed (the dropped HERRINGBONE variant previously played
    that role)."""
    ox, oy = patch_origin
    feature_tag = _centerpiece_feature_tag(spec, biome)
    for dx in range(spec.patch_dim):
        for dy in range(spec.patch_dim):
            tx, ty = ox + dx, oy + dy
            if not surface.in_bounds(tx, ty):
                continue
            surface.tiles[ty][tx] = Tile(
                terrain=Terrain.FLOOR,
                surface_type=SurfaceType.STREET,
            )
    feature_offset = (spec.patch_dim - spec.feature_dim) // 2
    fx = ox + feature_offset
    fy = oy + feature_offset
    if surface.in_bounds(fx, fy):
        surface.tiles[fy][fx].feature = feature_tag


def _build_town_surface(
    surface_id: str, buildings: list[Building],
    enclosure: Enclosure | None,
    cluster_plans: list[_ClusterPlan],
    size_class: str,
    config: _TownSizeConfig,
    centerpiece_rect: Rect | None = None,
    open_bounds: tuple[int, int, int, int] | None = None,
) -> Level:
    """Route the street network and stamp STREET / GARDEN / FIELD
    tiles across the walkable area.

    Phase 2 replaces the legacy "every walkable tile is STREET"
    fill with a tagged graph: routed STREET paths thread between
    cluster bboxes, GARDEN tiles cover cluster-internal walkable
    patches and FIELD tiles cover the periphery. See
    :mod:`nhc.sites._town_streets` for the routing details.

    ``open_bounds`` constrains the open-surface (non-palisade)
    walkable scan so hamlets keep their 1-tile VOID margin.
    Palisade-bearing sizes derive the walkable region from the
    enclosure polygon and ignore this parameter.
    """
    surface = Level.create_empty(
        surface_id, surface_id, 0,
        config.surface_width, config.surface_height,
    )
    surface.metadata.theme = "town"
    surface.metadata.ambient = "town"
    surface.metadata.prerevealed = True
    surface.metadata.street_material = _STREET_MATERIAL_BY_SIZE.get(
        size_class,
    )
    surface.metadata.pavement_material = (
        _PAVEMENT_MATERIAL_BY_SIZE.get(size_class)
    )
    blocked: set[tuple[int, int]] = set()
    for b in buildings:
        blocked |= b.base_shape.floor_tiles(b.base_rect)

    _, classification = compute_town_street_network(
        cluster_plans, enclosure,
        config.surface_width, config.surface_height,
        blocked, size_class,
        centerpiece_rect=centerpiece_rect,
        open_bounds=open_bounds,
    )
    paint_surface(surface, classification)
    paint_outer_grass_ring(surface, config.grass_ring_width)
    return surface


def _pave_courtyard_post_pass(
    surface: Level, palisade_rect: Rect,
) -> None:
    """Convert every GARDEN / FIELD tile **inside the palisade
    rect** to PAVEMENT.

    Runs at the end of ``assemble_town`` for size classes whose
    config sets ``paved_courtyard = True`` (cities). Door
    placement and vegetation scatter both read the pre-conversion
    ``surface_type`` so they keep their existing bias semantics
    (door bias toward GARDEN tiles, vegetation only on FIELD
    tiles); the post-pass runs *after* both so the visual
    surface ends up uniformly paved while the upstream placement
    logic stays intact.

    Restricted to the palisade interior so the FIELD tiles in
    the outer grass ring (placed by ``_paint_outer_grass_ring``
    for the trees / bushes outside the wall) survive the pave.

    Routed STREET tiles are NOT converted — they keep their own
    ``paved.*`` region (rendered as Brick FlemishBond via
    ``street_material``). The PAVEMENT tiles end up in a
    separate ``pavement.*`` region (rendered as Ashlar
    StaggeredJoint via ``pavement_material``), giving the city a
    visible split between the routed network and the open plaza.
    """
    for y in range(palisade_rect.y, palisade_rect.y2):
        for x in range(palisade_rect.x, palisade_rect.x2):
            if not surface.in_bounds(x, y):
                continue
            tile = surface.tiles[y][x]
            if tile.surface_type in (
                SurfaceType.GARDEN, SurfaceType.FIELD,
            ):
                tile.surface_type = SurfaceType.PAVEMENT


def _place_service_npcs(
    buildings: list[Building],
    role_assignments: dict[str, str],
    rng: random.Random,
) -> None:
    """Append NPC ``EntityPlacement``s to the ground floor of each
    building tagged with a service role that owns an NPC.

    The NPC stands on the room centre; extra payload (shop stock,
    temple services, adventurer level) is copied verbatim into the
    placement so ``_spawn_level_entities`` wires it up when the
    player enters the building.
    """
    by_id = {b.id: b for b in buildings}
    for bid, role in role_assignments.items():
        building = by_id[bid]
        ground = building.ground
        if not ground.rooms:
            continue
        room = ground.rooms[0]
        cx, cy = safe_floor_near(
            ground, *room.rect.center, room,
        )
        if role == "shop":
            ground.entities.append(_merchant_placement(cx, cy, rng))
        elif role == "temple":
            ground.entities.append(_priest_placement(cx, cy))
        elif role == "inn":
            ground.entities.append(_innkeeper_placement(cx, cy))


def _merchant_placement(
    cx: int, cy: int, rng: random.Random,
) -> EntityPlacement:
    """Merchant at the shop-room centre, stocked from depth-1 pool."""
    pool = SHOP_STOCK[1]
    ids, weights = zip(*pool)
    count = rng.randint(4, 7)
    stock = rng.choices(list(ids), weights=list(weights), k=count)
    seen: set[str] = set()
    unique: list[str] = []
    for iid in stock:
        if iid not in seen:
            seen.add(iid)
            unique.append(iid)
    return EntityPlacement(
        entity_type="creature", entity_id="merchant",
        x=cx, y=cy, extra={"shop_stock": unique},
    )


def _priest_placement(cx: int, cy: int) -> EntityPlacement:
    return EntityPlacement(
        entity_type="creature", entity_id="priest",
        x=cx, y=cy,
        extra={
            "temple_services": list(TEMPLE_SERVICES_DEFAULT),
            "shop_stock": list(TEMPLE_STOCK_DEFAULT),
        },
    )


def _adventurer_placement(
    x: int, y: int,
    anchor: tuple[int, int] | None = None,
) -> EntityPlacement:
    """Hirable level-1 adventurer.

    When ``anchor`` is supplied the placement carries errand-bias
    metadata so the spawner can wire an ``Errand`` anchor at entity
    creation: off-duty hirelings loiter near the inn door instead
    of drifting the entire surface.
    """
    extra: dict = {"adventurer_level": 1}
    if anchor is not None:
        extra["errand_anchor"] = anchor
        extra["errand_weight"] = 0.5
    return EntityPlacement(
        entity_type="creature", entity_id="adventurer",
        x=x, y=y, extra=extra,
    )


def _place_surface_adventurers(
    site: Site,
    role_assignments: dict[str, str],
    rng: random.Random,
) -> None:
    """Spawn unhired adventurers on the street next to each inn door.

    Hirelings are off-duty — they stroll the town via the errand
    behaviour with an ~50% destination bias toward the inn door, so
    the player can reliably find them to recruit. One per inn.
    """
    inn_ids = {
        bid for bid, role in role_assignments.items() if role == "inn"
    }
    if not inn_ids:
        return
    surface = site.surface

    # Reverse index: inn building id → (surface_x, surface_y)
    # using site.building_doors (surface-side tile → (bid, _, _)).
    inn_door_map: dict[str, tuple[int, int]] = {}
    for sxy, (bid, _bx, _by) in site.building_doors.items():
        if bid in inn_ids:
            inn_door_map[bid] = sxy

    occupied: set[tuple[int, int]] = {
        (p.x, p.y) for p in surface.entities
    }

    for bid, (dx, dy) in inn_door_map.items():
        spot = _nearest_street_tile_near(
            surface, dx, dy, occupied,
        )
        if spot is None:
            continue
        occupied.add(spot)
        surface.entities.append(
            _adventurer_placement(spot[0], spot[1], anchor=(dx, dy)),
        )


_OUTDOOR_SURFACE_TYPES = (
    SurfaceType.STREET, SurfaceType.GARDEN, SurfaceType.FIELD,
)


def _nearest_street_tile_near(
    surface: Level, cx: int, cy: int,
    occupied: set[tuple[int, int]],
) -> tuple[int, int] | None:
    """Pick a walkable, feature-free outdoor tile within 3
    Chebyshev of ``(cx, cy)`` and not in ``occupied``.

    STREET tiles are preferred; GARDEN / FIELD tiles fall back when
    no STREET tile is close enough. Phase 3's door bias keeps inn
    doors facing STREET so the preference path stays the common
    case after that phase lands.
    """
    best_by_priority: dict[
        SurfaceType, tuple[int, int, tuple[int, int]] | None,
    ] = {st: None for st in _OUTDOOR_SURFACE_TYPES}
    for y in range(
        max(0, cy - 3), min(surface.height, cy + 4),
    ):
        row = surface.tiles[y]
        for x in range(
            max(0, cx - 3), min(surface.width, cx + 4),
        ):
            if (x, y) == (cx, cy):
                continue
            if (x, y) in occupied:
                continue
            tile = row[x]
            if tile.surface_type not in _OUTDOOR_SURFACE_TYPES:
                continue
            if not tile.walkable:
                continue
            if tile.feature is not None:
                continue
            d = max(abs(x - cx), abs(y - cy))
            entry = best_by_priority[tile.surface_type]
            if entry is None or d < entry[0]:
                best_by_priority[tile.surface_type] = (d, 0, (x, y))
    for st in _OUTDOOR_SURFACE_TYPES:
        entry = best_by_priority[st]
        if entry is not None:
            return entry[2]
    return None


def _lock_shop_doors(
    buildings: list[Building],
    role_assignments: dict[str, str],
    rng: random.Random,
) -> None:
    """Convert one interior ``door_closed`` to ``door_locked`` on
    each shop building, gated by
    ``ARCHETYPE_CONFIG["shop"].locked_door_rate``.

    See ``design/building_interiors.md`` door rules: one locked
    door max per shop, door separating the smallest BSP leaf. The
    smallest-leaf picker in :func:`smallest_leaf_door` handles the
    BSP structure and the deterministic tie-break for equal leaf
    areas.
    """
    rate = ARCHETYPE_CONFIG["shop"].locked_door_rate
    if rate <= 0:
        return
    by_id = {b.id: b for b in buildings}
    for bid, role in role_assignments.items():
        if role != "shop":
            continue
        if rng.random() >= rate:
            continue
        ground = by_id[bid].ground
        door_tile = smallest_leaf_door(ground, by_id[bid])
        if door_tile is None:
            continue
        x, y = door_tile
        ground.tiles[y][x].feature = "door_locked"


def _connect_cross_building_doors(
    site: Site, cluster_plans: list[_ClusterPlan],
) -> None:
    """Add :class:`InteriorDoorLink`s for cluster-internal adjacent
    pairs whose 50/50 roll is ``True`` (Q8).

    Row clusters' adjacent members touch on the east / west edge;
    column clusters' adjacent members touch on the north / south
    edge. Each cluster carries the per-pair roll in
    :attr:`_ClusterPlan.interior_links_rolled` (one entry per
    adjacent pair, in left-to-right / top-to-bottom order). On
    success the helper stamps ``door_closed`` on the mirrored
    perimeter tiles of each shared floor and records the pair in
    :attr:`Site.interior_doors` (ground-floor only, legacy shape)
    and :attr:`Site.interior_door_links`.

    Solo / L-block / courtyard clusters skip this pass entirely;
    members in those archetypes are siblings sharing surfaces but
    not interiors.
    """
    by_id = {b.id: b for b in site.buildings}
    bid_by_index: dict[int, str] = {}
    for b in site.buildings:
        # Building ids follow the f"{site_id}_b{i}" pattern; pull
        # the trailing index back out so we can look up the cluster
        # member by its input index.
        try:
            idx = int(b.id.rsplit("_b", 1)[-1])
        except ValueError:
            continue
        bid_by_index[idx] = b.id

    for plan in cluster_plans:
        if plan.kind not in ("row", "column"):
            continue
        if len(plan.members) < 2:
            continue
        # Sort members by their layout axis so adjacency follows
        # the same order the layout used.
        sort_key = (
            (lambda m: m.rect.x) if plan.kind == "row"
            else (lambda m: m.rect.y)
        )
        ordered = sorted(plan.members, key=sort_key)
        for pair_idx, (left, right) in enumerate(
            zip(ordered, ordered[1:]),
        ):
            if pair_idx >= len(plan.interior_links_rolled):
                break
            if not plan.interior_links_rolled[pair_idx]:
                continue
            l_bid = bid_by_index.get(left.index)
            r_bid = bid_by_index.get(right.index)
            if l_bid is None or r_bid is None:
                continue
            l_building = by_id[l_bid]
            r_building = by_id[r_bid]
            if plan.kind == "row":
                _link_pair_per_floor(site, l_building, r_building, by_id)
            else:
                _link_pair_per_floor_vertical(
                    site, l_building, r_building, by_id,
                )


def _link_pair_per_floor_vertical(
    site: Site, top: Building, bottom: Building,
    by_id: dict[str, Building],
) -> None:
    """Stamp a north/south door pair on each floor shared by both
    buildings. ``top`` sits directly north of ``bottom``
    (``top.base_rect.y2 == bottom.base_rect.y``); the door lands on
    the south edge of ``top`` and the north edge of ``bottom`` at
    the centre of their horizontally overlapping perimeter
    columns."""
    top_south_xs = {
        x for (x, y) in top.shared_perimeter()
        if y == top.base_rect.y2 - 1
    }
    bottom_north_xs = {
        x for (x, y) in bottom.shared_perimeter()
        if y == bottom.base_rect.y
    }
    overlap = sorted(top_south_xs & bottom_north_xs)
    if not overlap:
        return
    x = overlap[len(overlap) // 2]
    ty = top.base_rect.y2 - 1
    by = bottom.base_rect.y

    shared_floor_count = min(len(top.floors), len(bottom.floors))
    for floor_idx in range(shared_floor_count):
        t_tile = top.floors[floor_idx].tiles[ty][x]
        b_tile = bottom.floors[floor_idx].tiles[by][x]
        if (t_tile.terrain is not Terrain.FLOOR
                or b_tile.terrain is not Terrain.FLOOR):
            continue
        stamp_building_door_on_floor(top, floor_idx, x, ty)
        stamp_building_door_on_floor(bottom, floor_idx, x, by)
        if floor_idx == 0:
            site.interior_doors[(top.id, x, ty)] = (bottom.id, x, by)
            site.interior_doors[(bottom.id, x, by)] = (top.id, x, ty)
        site.interior_door_links.append(InteriorDoorLink(
            from_building=top.id, to_building=bottom.id,
            floor=floor_idx,
            from_tile=(x, ty), to_tile=(x, by),
        ))


def _link_pair_per_floor(
    site: Site, left: Building, right: Building,
    by_id: dict[str, Building],
) -> None:
    """Stamp a door on each floor shared by both buildings.

    ``left`` sits to the west of ``right`` on the same row. The
    door lands on the east edge of ``left`` and the west edge of
    ``right`` at the centre of their vertically overlapping
    perimeter rows. Every floor uses the same ``(lx, ly)`` /
    ``(rx, ry)`` pair since floors share ``base_rect``.
    """
    left_east_ys = {
        y for (x, y) in left.shared_perimeter()
        if x == left.base_rect.x2 - 1
    }
    right_west_ys = {
        y for (x, y) in right.shared_perimeter()
        if x == right.base_rect.x
    }
    overlap = sorted(left_east_ys & right_west_ys)
    if not overlap:
        return
    y = overlap[len(overlap) // 2]
    lx = left.base_rect.x2 - 1
    rx = right.base_rect.x

    shared_floor_count = min(len(left.floors), len(right.floors))
    for floor_idx in range(shared_floor_count):
        l_tile = left.floors[floor_idx].tiles[y][lx]
        r_tile = right.floors[floor_idx].tiles[y][rx]
        # Only stamp if both tiles are interior floor tiles on
        # their respective Levels; a mismatched shape can leave a
        # wall where we expect floor.
        if (l_tile.terrain is not Terrain.FLOOR
                or r_tile.terrain is not Terrain.FLOOR):
            continue
        stamp_building_door_on_floor(left, floor_idx, lx, y)
        stamp_building_door_on_floor(right, floor_idx, rx, y)
        if floor_idx == 0:
            # Legacy ground-floor dict preserves the old mansion
            # movement contract so existing code keeps working.
            site.interior_doors[(left.id, lx, y)] = (
                right.id, rx, y,
            )
            site.interior_doors[(right.id, rx, y)] = (
                left.id, lx, y,
            )
        site.interior_door_links.append(InteriorDoorLink(
            from_building=left.id, to_building=right.id,
            floor=floor_idx,
            from_tile=(lx, y), to_tile=(rx, y),
        ))


def _innkeeper_placement(cx: int, cy: int) -> EntityPlacement:
    """Innkeeper near the inn-room centre; caller nudges the coord
    off the adventurer via :func:`safe_floor_near`."""
    return EntityPlacement(
        entity_type="creature", entity_id="innkeeper",
        x=cx, y=cy,
    )


# Villager headcount per town size class — sprinkled across street
# tiles to give the surface visible life. Pickpockets grow with
# settlement size: hamlets and small villages are too small to host
# an unseen thief, but towns and cities always carry one or two.
TOWN_VILLAGER_COUNT: dict[str, int] = {
    "hamlet": 2,
    "village": 4,
    "town": 6,
    "city": 8,
}
TOWN_PICKPOCKET_COUNT: dict[str, int] = {
    "hamlet": 0,
    "village": 0,
    "town": 1,
    "city": 2,
}


def _place_surface_villagers(
    site: Site, size_class: str, rng: random.Random,
) -> None:
    """Sprinkle villager + pickpocket placements on street tiles.

    Both use the same street-tile candidate pool and are mutually
    exclusive — a pickpocket never shares a spawn tile with a
    villager, and positions are unique across both populations.
    Villagers drive the town's baseline life; pickpockets lean on
    the errand-style wander to blend in visually (identical glyph,
    identical locale name) until they attempt a lift.
    """
    villager_count = TOWN_VILLAGER_COUNT.get(size_class, 0)
    pickpocket_count = TOWN_PICKPOCKET_COUNT.get(size_class, 0)
    total = villager_count + pickpocket_count
    if total <= 0:
        return

    surface = site.surface
    candidates: list[tuple[int, int]] = []
    for y in range(surface.height):
        row = surface.tiles[y]
        for x in range(surface.width):
            tile = row[x]
            if tile.surface_type != SurfaceType.STREET:
                continue
            if not tile.walkable:
                continue
            if tile.feature is not None:
                continue
            candidates.append((x, y))
    if not candidates:
        return

    rng.shuffle(candidates)
    used: set[tuple[int, int]] = set()
    cursor = 0

    def _take_next() -> tuple[int, int] | None:
        nonlocal cursor
        while cursor < len(candidates):
            spot = candidates[cursor]
            cursor += 1
            if spot in used:
                continue
            used.add(spot)
            return spot
        return None

    for _ in range(villager_count):
        spot = _take_next()
        if spot is None:
            break
        surface.entities.append(EntityPlacement(
            entity_type="creature", entity_id="villager",
            x=spot[0], y=spot[1],
        ))

    for _ in range(pickpocket_count):
        spot = _take_next()
        if spot is None:
            break
        surface.entities.append(EntityPlacement(
            entity_type="creature", entity_id="pickpocket",
            x=spot[0], y=spot[1],
        ))

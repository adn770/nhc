"""Cluster-based building packer for towns (Phase 1).

Replaces the legacy left-to-right row packer with grouped
clusters of 1-4 buildings -- row, column, L-block, courtyard or
solo. Each size class declares a target cluster count band and an
archetype-weight table; service roles anchor one-per-cluster
before residentials fill the remaining slots; row/column members
always touch, with a 50/50 cross-building link rolled per
adjacent pair (the "tenement" effect). Placement uses rejection
sampling with shrink-fallback: on exhaustion, the cluster's
archetype demotes one step (courtyard -> row, l_block -> row,
row -> solo) and retries.

See ``town_redesign_plan.md`` Phase 1 for the design rationale.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from itertools import permutations
from typing import TYPE_CHECKING

from nhc.dungeon.model import Rect

if TYPE_CHECKING:
    from nhc.sites._town_bsp import Partition, Plot
    from nhc.sites.town import _TownSizeConfig


# Service roles imported lazily inside helpers to avoid circular
# import (nhc.sites.town imports this module).


CLUSTER_BBOX_GAP = 1
"""Minimum tiles between two cluster bboxes so a street fits.

Reduced from 2 to 1 to enable the city tier's denser packing
(36-44 buildings across 12-16 clusters in a 104x86 inner rect).
A 1-tile gap still fits a single-width street between clusters;
spine paths in town/city widen to 2 tiles where possible but
gracefully shrink to 1 tile in pinch points between cluster
bboxes. Smaller settlements (hamlet/village/town) have plenty
of slack so the tighter gap doesn't visibly change their
layouts."""

MAX_CLUSTER_MEMBERS = 4
"""Cluster size cap (1..4)."""

MAX_PLACEMENT_ATTEMPTS = 50
"""Per-archetype rejection-sampling attempts before demotion."""

CLUSTER_COUNT_RANGE: dict[str, tuple[int, int]] = {
    "hamlet": (2, 2),
    "village": (2, 3),
    "town": (3, 4),
    # City progressively bumped (4, 6) → (5, 6) → (6, 8) → (12, 16)
    # so the cluster partitioner can fit the (36, 44) building
    # range with the ``MAX_CLUSTER_MEMBERS = 4`` cap.
    # ``ceil(44 / 4) = 11`` is the minimum cluster count that lets
    # ``_partition_sizes`` hand out 44 buildings without producing
    # a cluster of size 5+; the lower bound of 12 keeps a touch of
    # margin and the upper bound of 16 gives the city visibly more
    # distinct cluster bboxes (and thus more routed side streets
    # between them) than smaller tiers.
    "city": (12, 16),
}
"""Inclusive (lo, hi) target cluster count per size_class (Q13)."""


CLUSTER_ARCHETYPE_WEIGHTS: dict[str, dict[str, float]] = {
    "hamlet": {"row": 0.70, "column": 0.30},
    "village": {"row": 0.50, "column": 0.25, "l_block": 0.25},
    "town": {
        "row": 0.35, "column": 0.20, "l_block": 0.30,
        "courtyard": 0.15,
    },
    "city": {
        "row": 0.30, "column": 0.15, "l_block": 0.30,
        "courtyard": 0.25,
    },
}
"""Per-size-class archetype weights (Q6). Solo is implicit and
 fires for single-member clusters (Q17) without consulting this
 table."""


# How many members each archetype accepts.
_ARCHETYPE_ARITY: dict[str, tuple[int, int]] = {
    "row": (2, MAX_CLUSTER_MEMBERS),
    "column": (2, MAX_CLUSTER_MEMBERS),
    "l_block": (3, 3),
    "courtyard": (4, 4),
    "solo": (1, 1),
}


# Demotion chain used by rejection-sampling shrink-fallback (Q11).
_DEMOTE_NEXT: dict[str, str | None] = {
    "courtyard": "row",
    "l_block": "row",
    "row": "split",
    "column": "split",
    "solo": None,
}
"""``"split"`` is a sentinel meaning "split this cluster into
solo clusters and place them individually"."""


# Inner garden patch dim used by L-block / courtyard layouts.
_PATCH_MIN = 3


@dataclass
class _ClusterMember:
    """One building inside a cluster.

    ``index`` points back into the original ``roles`` / ``sizes``
    lists passed to :func:`_cluster_pack`. ``rect`` is in
    absolute surface coordinates after :func:`_place_clusters`.
    """

    index: int
    role: str
    size: tuple[int, int]
    rect: Rect


@dataclass
class _ClusterPlan:
    """A placed cluster."""

    kind: str
    members: list[_ClusterMember] = field(default_factory=list)
    bbox: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    interior_links_rolled: list[bool] = field(default_factory=list)
    """50/50 link rolls per adjacent pair (Q8). Index ``i`` is the
     roll between ``members[i]`` and ``members[i + 1]`` ordered as
     they were laid out (left-to-right for row, top-to-bottom for
     column). Empty for solo / l_block / courtyard."""


# ── Layout helpers (cluster-local coords) ────────────────────


def _layout_solo(member_size: tuple[int, int]) -> list[Rect]:
    w, h = member_size
    return [Rect(0, 0, w, h)]


def _layout_row(
    member_sizes: list[tuple[int, int]],
) -> list[Rect]:
    """Place buildings left-to-right, all touching, top-aligned."""
    rects: list[Rect] = []
    x_cursor = 0
    for w, h in member_sizes:
        rects.append(Rect(x_cursor, 0, w, h))
        x_cursor += w
    return rects


def _layout_column(
    member_sizes: list[tuple[int, int]],
) -> list[Rect]:
    """Stack buildings top-to-bottom, all touching, left-aligned."""
    rects: list[Rect] = []
    y_cursor = 0
    for w, h in member_sizes:
        rects.append(Rect(0, y_cursor, w, h))
        y_cursor += h
    return rects


def _l_block_ordering(
    member_sizes: list[tuple[int, int]],
) -> tuple[int, int, int] | None:
    """Pick (A, B, C) so the L is well-formed.

    A is the elbow at top-left, B extends the horizontal arm
    rightward and C extends the vertical arm downward. The arms
    only avoid overlapping when ``wc <= wa`` (C fits below A
    without poking into B's column) or ``hb <= ha`` (B fits to
    the right of A without poking into C's row). Returns the
    permutation indices into ``member_sizes`` or ``None`` when
    no permutation produces a clean L.
    """
    for i_a, i_b, i_c in permutations(range(3)):
        wa, ha = member_sizes[i_a]
        _, hb = member_sizes[i_b]
        wc, _ = member_sizes[i_c]
        if wc <= wa or hb <= ha:
            return (i_a, i_b, i_c)
    return None


def _layout_l_block(
    member_sizes: list[tuple[int, int]],
) -> list[Rect]:
    """Three buildings forming an L with the elbow at top-left.

    Caller must order ``member_sizes`` so that members[0] is the
    elbow (inner-corner), members[1] extends the horizontal arm
    and members[2] extends the vertical arm. Use
    :func:`_l_block_ordering` to pick a valid ordering before
    calling.
    """
    assert len(member_sizes) == 3
    (wa, ha), (wb, hb), (wc, hc) = member_sizes
    a = Rect(0, 0, wa, ha)
    b = Rect(wa, 0, wb, hb)
    c = Rect(0, ha, wc, hc)
    return [a, b, c]


def _layout_courtyard(
    member_sizes: list[tuple[int, int]],
) -> list[Rect]:
    """Four buildings around a 3x3 inner patch.

    Members are interpreted as N (top), E (right), S (bottom),
    W (left). Each is centred along its edge of the inner patch.
    """
    assert len(member_sizes) == 4
    (wn, hn), (we, he), (ws, hs), (ww, hw) = member_sizes
    middle_w = max(wn, _PATCH_MIN, ws)
    middle_h = max(hw, _PATCH_MIN, he)

    n = Rect(ww + (middle_w - wn) // 2, 0, wn, hn)
    s = Rect(ww + (middle_w - ws) // 2, hn + middle_h, ws, hs)
    w_rect = Rect(0, hn + (middle_h - hw) // 2, ww, hw)
    e = Rect(ww + middle_w, hn + (middle_h - he) // 2, we, he)
    return [n, e, s, w_rect]


def _layout_for(
    archetype: str, member_sizes: list[tuple[int, int]],
) -> list[Rect]:
    if archetype == "solo":
        return _layout_solo(member_sizes[0])
    if archetype == "row":
        return _layout_row(member_sizes)
    if archetype == "column":
        return _layout_column(member_sizes)
    if archetype == "l_block":
        return _layout_l_block(member_sizes)
    if archetype == "courtyard":
        return _layout_courtyard(member_sizes)
    raise ValueError(f"unknown cluster archetype: {archetype!r}")


def _cluster_dims(rects: list[Rect]) -> tuple[int, int]:
    """Return the cluster's footprint width / height (no buffer)."""
    max_x = max(r.x2 for r in rects)
    max_y = max(r.y2 for r in rects)
    return max_x, max_y


def _bbox_for(origin: tuple[int, int], dims: tuple[int, int]) -> Rect:
    """Return the cluster bbox = footprint + 1-tile buffer ring."""
    ox, oy = origin
    w, h = dims
    return Rect(ox - 1, oy - 1, w + 2, h + 2)


# ── Partitioning ─────────────────────────────────────────────


def _pick_cluster_count(
    n_buildings: int, size_class: str, rng: random.Random,
) -> int:
    lo, hi = CLUSTER_COUNT_RANGE[size_class]
    # Cluster count cannot exceed n_buildings (each cluster
    # carries at least one member).
    hi = min(hi, n_buildings)
    lo = min(lo, hi)
    if lo == hi:
        return lo
    return rng.randint(lo, hi)


def _partition_sizes(
    n: int, k: int, rng: random.Random,
) -> list[int]:
    """Distribute ``n`` members across ``k`` clusters in [1, 4]
    each. Mostly even with a handful of random ±1 swaps to
    introduce size variety (so courtyards / solos coexist)."""
    base, rem = divmod(n, k)
    sizes = [base + 1 if i < rem else base for i in range(k)]
    # A few balanced ±1 swaps; clamp to [1, MAX_CLUSTER_MEMBERS]. Needs
    # at least two clusters to swap between (per-plot fill can ask for a
    # single cluster; the global packer never does).
    swap_attempts = max(2, k) if k >= 2 else 0
    for _ in range(swap_attempts):
        i, j = rng.sample(range(k), 2)
        if (sizes[i] > 1 and sizes[j] < MAX_CLUSTER_MEMBERS):
            if rng.random() < 0.5:
                sizes[i] -= 1
                sizes[j] += 1
    rng.shuffle(sizes)
    assert sum(sizes) == n
    assert all(1 <= s <= MAX_CLUSTER_MEMBERS for s in sizes)
    return sizes


def _assign_members(
    roles: list[str], partition: list[int], rng: random.Random,
) -> list[list[int]]:
    """Group input indices into ``len(partition)`` clusters,
    anchoring services across clusters before filling residentials.

    Returns: list of cluster index lists, ordered to match
    ``partition``."""
    from nhc.sites.town import SERVICE_ROLES

    k = len(partition)
    indices = list(range(len(roles)))
    service_idx = [i for i in indices if roles[i] in SERVICE_ROLES]
    rest_idx = [i for i in indices if roles[i] not in SERVICE_ROLES]
    rng.shuffle(service_idx)
    rng.shuffle(rest_idx)

    clusters: list[list[int]] = [[] for _ in range(k)]

    # Anchor pass: first K service indices land one per cluster.
    for cluster_idx, sidx in enumerate(service_idx[:k]):
        clusters[cluster_idx].append(sidx)
    leftover = service_idx[k:] + rest_idx

    # Fill remaining slots, picking the cluster with the most
    # remaining capacity each time. Ties broken by RNG so the
    # archetype roll downstream gets a varied member mix.
    for idx in leftover:
        slack = [
            (partition[i] - len(clusters[i]), rng.random(), i)
            for i in range(k)
        ]
        slack.sort(reverse=True)
        target = slack[0][2]
        clusters[target].append(idx)
    return clusters


# ── Archetype rolling ────────────────────────────────────────


def _feasible_archetypes(n_members: int) -> list[str]:
    feasible: list[str] = []
    for arch, (lo, hi) in _ARCHETYPE_ARITY.items():
        if arch == "solo":
            continue
        if lo <= n_members <= hi:
            feasible.append(arch)
    return feasible


def _roll_archetype(
    n_members: int, size_class: str, rng: random.Random,
) -> str:
    """Pick a cluster archetype based on size_class weights and
    member-count feasibility (Q6 + Q17)."""
    if n_members == 1:
        return "solo"
    weights_by_arch = CLUSTER_ARCHETYPE_WEIGHTS[size_class]
    feasible = [
        a for a in _feasible_archetypes(n_members) if a in weights_by_arch
    ]
    if not feasible:
        return "row"
    weights = [weights_by_arch[a] for a in feasible]
    return rng.choices(feasible, weights=weights)[0]


# ── Layout orchestration per cluster ─────────────────────────


def _layout_plan(
    roles: list[str],
    sizes: list[tuple[int, int]],
    member_indices: list[int],
    archetype: str,
    rng: random.Random,
) -> _ClusterPlan:
    """Build a :class:`_ClusterPlan` (rects in cluster-local
    coords). The bbox is set later by :func:`_place_clusters`."""
    member_sizes = [sizes[i] for i in member_indices]

    if archetype == "l_block":
        ordering = _l_block_ordering(member_sizes)
        if ordering is None:
            # No permutation forms a clean L for these sizes;
            # fall back to a row before placement runs.
            archetype = "row"
        else:
            member_indices = [member_indices[i] for i in ordering]
            member_sizes = [member_sizes[i] for i in ordering]

    rects = _layout_for(archetype, member_sizes)
    members = [
        _ClusterMember(
            index=member_indices[i], role=roles[member_indices[i]],
            size=member_sizes[i], rect=rects[i],
        )
        for i in range(len(member_indices))
    ]
    interior_links: list[bool] = []
    if archetype in ("row", "column") and len(members) >= 2:
        for _ in range(len(members) - 1):
            interior_links.append(rng.random() < 0.5)
    return _ClusterPlan(
        kind=archetype, members=members,
        bbox=Rect(0, 0, 0, 0),
        interior_links_rolled=interior_links,
    )


def _translate_plan(
    plan: _ClusterPlan, origin: tuple[int, int],
) -> None:
    """Translate cluster-local rects to absolute coords + set bbox."""
    ox, oy = origin
    for m in plan.members:
        m.rect = Rect(m.rect.x + ox, m.rect.y + oy,
                      m.rect.width, m.rect.height)
    dims_w, dims_h = _cluster_dims([m.rect for m in plan.members])
    plan.bbox = Rect(
        ox - 1, oy - 1,
        (dims_w - ox) + 2, (dims_h - oy) + 2,
    )


# ── Placement (rejection sampling + demotion) ────────────────


def _bboxes_overlap_with_gap(
    a: Rect, b: Rect, gap: int,
) -> bool:
    """``True`` when ``a`` and ``b`` are within ``gap`` tiles of
    each other on both axes (i.e. would block a 2-tile street).

    Inlined hot path (called millions of times during cluster
    packing): the axis separation is ``< gap`` exactly when neither
    box is ``>= gap`` past the other, so short-circuit on the first
    axis that clears the gap instead of building ``max()`` temps.
    Equivalent to the old ``max(0, max(...)) < gap`` form for the
    positive ``gap`` this is always called with.
    """
    if a.x - b.x2 >= gap or b.x - a.x2 >= gap:
        return False
    if a.y - b.y2 >= gap or b.y - a.y2 >= gap:
        return False
    return True


class _BboxGrid:
    """Uniform-grid spatial index for gap-overlap queries.

    Pure acceleration for cluster packing: ``overlaps_any`` returns
    the same boolean a linear scan + :func:`_bboxes_overlap_with_gap`
    would, so placement stays seed-identical — it just avoids testing
    far-apart rects. Rects are bucketed by the cells they cover;
    a query scans only the buckets its gap-expanded bbox touches.

    Coverage guarantee: a query bbox gap-overlaps a rect ``r`` iff the
    bbox expanded by ``gap`` intersects ``r``, so inserting ``r`` by
    its own cells and querying the gap-expanded cell range can never
    miss an overlapping rect.
    """

    __slots__ = ("gap", "cell", "buckets")

    def __init__(self, gap: int, cell: int = 16) -> None:
        self.gap = gap
        self.cell = cell
        self.buckets: dict[tuple[int, int], list[Rect]] = {}

    def _cells(self, rect: Rect, pad: int):
        c = self.cell
        return (
            (rect.x - pad) // c, (rect.x2 - 1 + pad) // c,
            (rect.y - pad) // c, (rect.y2 - 1 + pad) // c,
        )

    def add(self, rect: Rect) -> None:
        x0, x1, y0, y1 = self._cells(rect, 0)
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                self.buckets.setdefault((cx, cy), []).append(rect)

    def overlaps_any(self, bbox: Rect) -> bool:
        x0, x1, y0, y1 = self._cells(bbox, self.gap)
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                bucket = self.buckets.get((cx, cy))
                if not bucket:
                    continue
                for r in bucket:
                    if _bboxes_overlap_with_gap(bbox, r, self.gap):
                        return True
        return False


def _try_place_plan(
    plan: _ClusterPlan,
    placed_bboxes: list[Rect],
    forbidden_rects: list[Rect],
    bounds: tuple[int, int, int, int],
    rng: random.Random,
    random_attempts: int = MAX_PLACEMENT_ATTEMPTS,
    scan_shuffle: bool = True,
) -> bool:
    """Search for a valid origin for ``plan``. Random sampling
    first; on exhaustion, fall back to a deterministic scan so any
    geometrically-valid position is found. Mutates ``plan`` on success.

    Defaults reproduce the global cluster packer exactly (random
    sampling + shuffled scan). The per-plot fill passes
    ``random_attempts=0, scan_shuffle=False`` for a top-left scan that
    packs clusters into a corner and keeps the remaining free space
    contiguous — so a tight plot can still seat every building."""
    min_x, min_y, max_x, max_y = bounds
    rects = [m.rect for m in plan.members]
    cluster_w, cluster_h = _cluster_dims(rects)
    ox_lo, ox_hi = min_x + 1, max_x - cluster_w - 1
    oy_lo, oy_hi = min_y + 1, max_y - cluster_h - 1
    if ox_hi < ox_lo or oy_hi < oy_lo:
        return False

    # Spatial index over everything the candidate must avoid. Built
    # once per placement (O(rects)) then queried per attempt /
    # scan-cell (O(nearby)), replacing the old O(attempts × rects)
    # linear scans. placed_bboxes already includes forbidden_rects
    # (see _place_clusters), but adding both is harmless (a dup is
    # just tested twice) and keeps this independent of that invariant.
    index = _BboxGrid(CLUSTER_BBOX_GAP)
    for p in placed_bboxes:
        index.add(p)
    for fr in forbidden_rects:
        index.add(fr)

    def _check(ox: int, oy: int) -> bool:
        bbox = _bbox_for((ox, oy), (cluster_w, cluster_h))
        return not index.overlaps_any(bbox)

    valid_origin: tuple[int, int] | None = None
    for _ in range(random_attempts):
        ox = rng.randint(ox_lo, ox_hi)
        oy = rng.randint(oy_lo, oy_hi)
        if _check(ox, oy):
            valid_origin = (ox, oy)
            break
    if valid_origin is None:
        # Deterministic scan. Shuffled (global packer) keeps placement
        # seed-dependent and unbiased; unshuffled (per-plot fill) packs
        # top-left and keeps the free space contiguous.
        ox_range = list(range(ox_lo, ox_hi + 1))
        oy_range = list(range(oy_lo, oy_hi + 1))
        if scan_shuffle:
            rng.shuffle(ox_range)
            rng.shuffle(oy_range)
        for ox in ox_range:
            for oy in oy_range:
                if _check(ox, oy):
                    valid_origin = (ox, oy)
                    break
            if valid_origin is not None:
                break
    if valid_origin is None:
        return False

    ox, oy = valid_origin
    for m in plan.members:
        m.rect = Rect(
            m.rect.x + ox, m.rect.y + oy,
            m.rect.width, m.rect.height,
        )
    plan.bbox = _bbox_for(valid_origin, (cluster_w, cluster_h))
    return True


def _place_clusters(
    plans: list[_ClusterPlan],
    bounds: tuple[int, int, int, int],
    forbidden_rects: list[Rect],
    rng: random.Random,
    random_attempts: int = MAX_PLACEMENT_ATTEMPTS,
    scan_shuffle: bool = True,
) -> list[_ClusterPlan]:
    """Place each cluster bbox via rejection sampling. On
    exhaustion, demote the archetype one step and retry. ``solo``
    splits a row/column cluster into per-member solos placed
    independently. ``bounds`` is ``(min_x, min_y, max_x, max_y)``
    in surface coords (``max_*`` exclusive); clusters are placed
    inside this region with a 1-tile internal buffer.

    ``random_attempts`` / ``scan_shuffle`` are forwarded to
    :func:`_try_place_plan`; the defaults reproduce the global packer,
    the per-plot fill passes ``0`` / ``False`` for contiguous top-left
    packing."""
    placed_bboxes: list[Rect] = list(forbidden_rects)
    out: list[_ClusterPlan] = []

    def _place(plan: _ClusterPlan) -> bool:
        return _try_place_plan(
            plan, placed_bboxes, forbidden_rects, bounds, rng,
            random_attempts, scan_shuffle,
        )

    for plan in plans:
        success = _place(plan)
        current = plan
        while not success:
            next_kind = _DEMOTE_NEXT.get(current.kind)
            if next_kind is None:
                break
            if next_kind == "split":
                # Solo each member independently.
                solo_plans = _split_into_solos(current, rng)
                for sp in solo_plans:
                    if _place(sp):
                        placed_bboxes.append(sp.bbox)
                        out.append(sp)
                # Original ``plan`` is replaced by the solos.
                current = None
                break
            # Demote to next_kind (e.g. courtyard -> row).
            member_sizes = [m.size for m in current.members]
            new_rects = _layout_for(next_kind, member_sizes)
            for i, r in enumerate(new_rects):
                current.members[i].rect = r
            current.kind = next_kind
            current.interior_links_rolled = []
            if next_kind in ("row", "column"):
                for _ in range(len(current.members) - 1):
                    current.interior_links_rolled.append(
                        rng.random() < 0.5,
                    )
            success = _place(current)

        if success and current is not None:
            placed_bboxes.append(current.bbox)
            out.append(current)
    return out


def _split_into_solos(
    plan: _ClusterPlan, rng: random.Random,
) -> list[_ClusterPlan]:
    solos: list[_ClusterPlan] = []
    for m in plan.members:
        rects = _layout_solo(m.size)
        new_member = _ClusterMember(
            index=m.index, role=m.role, size=m.size, rect=rects[0],
        )
        solos.append(_ClusterPlan(
            kind="solo", members=[new_member],
            bbox=Rect(0, 0, 0, 0),
            interior_links_rolled=[],
        ))
    return solos


# ── Public entry points ──────────────────────────────────────


def _cluster_pack(
    roles: list[str],
    sizes: list[tuple[int, int]],
    config: _TownSizeConfig,
    size_class: str,
    rng: random.Random,
    forbidden_rects: list[Rect] | None = None,
    bounds: tuple[int, int, int, int] | None = None,
) -> list[_ClusterPlan]:
    """Top-level cluster packer (drop-in replacement for the legacy
    greedy row packer).

    ``roles`` and ``sizes`` are parallel input lists, one per
    building. Returns a list of placed :class:`_ClusterPlan`s
    whose member rects span every input index.

    ``bounds`` is the ``(min_x, min_y, max_x, max_y)`` region in
    surface coords inside which clusters land (``max_*``
    exclusive). When ``None``, falls back to a region the size of
    ``config.palisade_outer_width × palisade_outer_height``
    rooted at ``(0, 0)`` — the legacy default that test suites
    targeting the packer in isolation expect. Production callers
    (``assemble_town``) always supply explicit bounds derived
    from :func:`nhc.sites.town._buildable_bounds` so building
    placement honours the 1-tile VOID margin contract.
    """
    n = len(roles)
    forbidden_rects = list(forbidden_rects or [])
    if n == 0:
        return []
    k = _pick_cluster_count(n, size_class, rng)
    partition = _partition_sizes(n, k, rng)
    cluster_indices = _assign_members(roles, partition, rng)
    plans: list[_ClusterPlan] = []
    for member_indices in cluster_indices:
        if not member_indices:
            continue
        archetype = _roll_archetype(
            len(member_indices), size_class, rng,
        )
        plans.append(_layout_plan(
            roles, sizes, member_indices, archetype, rng,
        ))

    # Place largest bboxes first so big courtyards don't get
    # squeezed by previously-placed solos.
    plans.sort(
        key=lambda p: -(_cluster_dims(
            [m.rect for m in p.members],
        )[0] * _cluster_dims(
            [m.rect for m in p.members],
        )[1]),
    )
    if bounds is None:
        bounds = (
            0, 0,
            config.palisade_outer_width,
            config.palisade_outer_height,
        )
    return _place_clusters(plans, bounds, forbidden_rects, rng)


def _placements_from_clusters(
    n_buildings: int, plans: list[_ClusterPlan],
) -> list[tuple[int, int, int, int]]:
    """Flatten cluster member rects to a per-building tuple list
    parallel to the original ``roles`` / ``sizes`` inputs."""
    placements: list[tuple[int, int, int, int] | None] = [
        None
    ] * n_buildings
    for plan in plans:
        for m in plan.members:
            placements[m.index] = (
                m.rect.x, m.rect.y, m.rect.width, m.rect.height,
            )
    # Drop any None (cluster fully dropped) -- caller compacts.
    return [p for p in placements if p is not None]


# ── Phase 2: BSP-neighbourhood per-plot fill ─────────────────
#
# Replaces the global ``_cluster_pack`` flow: the BSP partitioner
# (``nhc.sites._town_bsp``) hands a few neighbourhood plots, and we
# fill each plot independently. See design/town_generator.md §3.3-§3.5
# (D3/D4/D5/D6/D8/D10) and the Q1-Q6 interview answers.


# Plot massing tier (D10): a plot hosting the big plaza is the civic
# "core", one hosting a small plaza a residential "pocket", a plain
# plot the "edge". Drives both the service-role bias and the size skew.
_SERVICE_TIER_WEIGHT: dict[str, float] = {
    "core": 4.0, "pocket": 1.5, "edge": 1.0,
}

# Archetype-to-plot-aspect bias (D3): a clearly wide plot favours rows,
# a tall plot columns, a square plot courtyards / L-blocks.
_WIDE_ASPECT = 1.3
_TALL_ASPECT = 1.0 / 1.3
_ASPECT_BOOST = 4.0
_SQUARE_BOOST = 2.5


def _service_roles() -> tuple[str, ...]:
    from nhc.sites.town import SERVICE_ROLES

    return SERVICE_ROLES


def _archetype_config():
    from nhc.dungeon.interior.registry import ARCHETYPE_CONFIG

    return ARCHETYPE_CONFIG


def _plot_tier(plot: Plot) -> str:
    if plot.plaza is None:
        return "edge"
    return "core" if plot.plaza.tier == "big" else "pocket"


def _packable_area(plot: Plot) -> int:
    """Plot area available for buildings: the leaf minus its plaza
    rect (the gutter is already outside the leaf). N4."""
    area = plot.rect.width * plot.rect.height
    if plot.plaza is not None:
        area -= plot.plaza.rect.width * plot.plaza.rect.height
    return max(1, area)


# Gross tiles a plot needs per building (footprint + buffer + packing
# slack). Caps a plot's budget so a short / narrow plot isn't handed
# more buildings than it can physically seat; the excess goes to the
# global remainder pool (B4) and is placed wherever the town has room.
_BUILDING_CELL = 135


def _split_budget(plots: list[Plot], n: int) -> list[int]:
    """Area-proportional split of ``n`` buildings across plots by
    packable area, each plot capped at its physical capacity (D8/B4).
    Returns budgets that may sum to **less** than ``n`` — the shortfall
    is the global remainder pool placed by the spill pass."""
    areas = [_packable_area(p) for p in plots]
    caps = [max(1, a // _BUILDING_CELL) for a in areas]
    total = sum(areas) or 1
    raw = [n * a / total for a in areas]
    budgets = [min(int(raw[i]), caps[i]) for i in range(len(plots))]
    # Hand out the rounding remainder to plots that still have capacity,
    # largest spare capacity first.
    remaining = min(n, sum(caps)) - sum(budgets)
    while remaining > 0:
        spare = [
            (caps[i] - budgets[i], i)
            for i in range(len(plots)) if budgets[i] < caps[i]
        ]
        if not spare:
            break
        spare.sort(reverse=True)
        budgets[spare[0][1]] += 1
        remaining -= 1
    return budgets


def _distribute_indices(
    tiers: list[str],
    roles: list[str],
    budgets: list[int],
    rng: random.Random,
) -> tuple[list[list[int]], list[int]]:
    """Assign each building index to a plot, respecting per-plot
    budgets. Service roles are softly biased toward the core (big-plaza)
    plot (D5); residentials fill the rest by remaining capacity. Indices
    that don't fit any plot's budget go to the returned **leftover** pool
    (B4), placed town-wide by the spill pass."""
    service_roles = _service_roles()
    n_plots = len(tiers)
    remaining = list(budgets)
    assigned: list[list[int]] = [[] for _ in range(n_plots)]
    leftover: list[int] = []
    service_idx = [i for i, r in enumerate(roles) if r in service_roles]
    rest_idx = [i for i, r in enumerate(roles) if r not in service_roles]
    rng.shuffle(service_idx)
    rng.shuffle(rest_idx)

    def _pick(service: bool) -> int | None:
        cands = [i for i in range(n_plots) if remaining[i] > 0]
        if not cands:
            return None
        if service:
            weights = [
                remaining[i] * _SERVICE_TIER_WEIGHT[tiers[i]] for i in cands
            ]
        else:
            weights = [float(remaining[i]) for i in cands]
        choice = rng.choices(cands, weights=weights)[0]
        remaining[choice] -= 1
        return choice

    for idx in service_idx:
        plot_i = _pick(service=True)
        (leftover if plot_i is None else assigned[plot_i]).append(idx)
    for idx in rest_idx:
        plot_i = _pick(service=False)
        (leftover if plot_i is None else assigned[plot_i]).append(idx)
    return assigned, leftover


def _draw_size_tiered(
    role: str, tier: str, rng: random.Random,
) -> tuple[int, int]:
    """Draw ``(w, h)`` from the role's ``size_range``, skewed within the
    band by the plot's massing tier (D10/Q3). Residential only: core =
    ``max`` of two draws (grand), edge = ``min`` (humble), pocket /
    services = a single neutral draw. The value never leaves the role's
    own band, so no role grows into another's and plot-fit is safe."""
    lo, hi = _archetype_config()[role].size_range

    def _draw() -> int:
        return rng.randint(lo, hi)

    if role == "residential" and tier == "core":
        return (max(_draw(), _draw()), max(_draw(), _draw()))
    if role == "residential" and tier == "edge":
        return (min(_draw(), _draw()), min(_draw(), _draw()))
    return (_draw(), _draw())


def _plot_cluster_count(n: int) -> int:
    """Clusters for a plot holding ``n`` buildings: ~2.5 per cluster,
    never below ``ceil(n / MAX_CLUSTER_MEMBERS)``."""
    if n <= 1:
        return 1
    return max(math.ceil(n / MAX_CLUSTER_MEMBERS), round(n / 2.5))


def _roll_archetype_for_plot(
    n_members: int, size_class: str, plot_rect: Rect, rng: random.Random,
) -> str:
    """Like :func:`_roll_archetype` but boosts the archetype that fits
    the plot's aspect ratio (D3)."""
    if n_members == 1:
        return "solo"
    base = CLUSTER_ARCHETYPE_WEIGHTS[size_class]
    feasible = [a for a in _feasible_archetypes(n_members) if a in base]
    if not feasible:
        return "row"
    aspect = plot_rect.width / max(1, plot_rect.height)
    weights: list[float] = []
    for arch in feasible:
        weight = base[arch]
        if arch == "row" and aspect >= _WIDE_ASPECT:
            weight *= _ASPECT_BOOST
        elif arch == "column" and aspect <= _TALL_ASPECT:
            weight *= _ASPECT_BOOST
        elif (
            arch in ("courtyard", "l_block")
            and _TALL_ASPECT < aspect < _WIDE_ASPECT
        ):
            weight *= _SQUARE_BOOST
        weights.append(weight)
    return rng.choices(feasible, weights=weights)[0]


def _cluster_plot(
    plot_indices: list[int],
    roles: list[str],
    sizes: list[tuple[int, int]],
    size_class: str,
    plot_rect: Rect,
    rng: random.Random,
) -> list[_ClusterPlan]:
    """Group one plot's buildings into clusters (service-anchored,
    archetype fit to plot aspect) in cluster-local coords."""
    n = len(plot_indices)
    if n == 0:
        return []
    k = _plot_cluster_count(n)
    partition = _partition_sizes(n, k, rng)
    plot_roles = [roles[i] for i in plot_indices]
    local_groups = _assign_members(plot_roles, partition, rng)
    plans: list[_ClusterPlan] = []
    for group in local_groups:
        if not group:
            continue
        global_indices = [plot_indices[li] for li in group]
        archetype = _roll_archetype_for_plot(
            len(global_indices), size_class, plot_rect, rng,
        )
        plans.append(_layout_plan(
            roles, sizes, global_indices, archetype, rng,
        ))
    # Place the largest cluster bboxes first so big courtyards aren't
    # squeezed out by previously-placed solos (mirrors _cluster_pack).
    plans.sort(key=lambda p: -_plan_footprint_area(p))
    return plans


def _plan_footprint_area(plan: _ClusterPlan) -> int:
    width, height = _cluster_dims([m.rect for m in plan.members])
    return width * height


def fill_partition(
    partition: Partition,
    roles: list[str],
    size_class: str,
    rng: random.Random,
) -> list[_ClusterPlan]:
    """Fill a BSP partition: distribute the roster across plots
    (area-proportional, service-biased), draw tier-skewed sizes, cluster
    and pack each plot independently, then spill overflow into any plot
    with slack — dropping residential-first and never a service role
    (B4/Q4). Returns the placed :class:`_ClusterPlan`s; member ``index``
    fields point back into ``roles``."""
    n = len(roles)
    if n == 0:
        return []
    plots = partition.plots
    tiers = [_plot_tier(p) for p in plots]
    budgets = _split_budget(plots, n)
    assigned, leftover = _distribute_indices(tiers, roles, budgets, rng)

    sizes: list[tuple[int, int]] = [(0, 0)] * n
    # Leftover-pool buildings have no home plot; draw them neutrally.
    for idx in leftover:
        sizes[idx] = _draw_size_tiered(roles[idx], "pocket", rng)
    all_plans: list[_ClusterPlan] = []

    for plot_i, plot in enumerate(plots):
        tier = tiers[plot_i]
        for idx in assigned[plot_i]:
            sizes[idx] = _draw_size_tiered(roles[idx], tier, rng)
        bounds = (plot.rect.x, plot.rect.y, plot.rect.x2, plot.rect.y2)
        forbidden = [plot.plaza.rect] if plot.plaza is not None else []
        plans = _cluster_plot(
            assigned[plot_i], roles, sizes, size_class, plot.rect, rng,
        )
        placed = _place_clusters(
            plans, bounds, forbidden, rng,
            random_attempts=0, scan_shuffle=False,
        )
        all_plans.extend(placed)

    # Single town-wide keep-out list for the spill pass: building bboxes
    # + plaza rects + gutters (so spilled buildings never block a street).
    occupied: list[Rect] = [p.bbox for p in all_plans]
    occupied += [pl.plaza.rect for pl in plots if pl.plaza is not None]
    occupied += list(partition.gutters)
    interior = partition.interior
    interior_bounds = (interior.x, interior.y, interior.x2, interior.y2)
    _spill_remainder(
        all_plans, occupied, roles, sizes, n, interior_bounds, rng,
    )
    return all_plans


def _spill_remainder(
    all_plans: list[_ClusterPlan],
    occupied: list[Rect],
    roles: list[str],
    sizes: list[tuple[int, int]],
    n: int,
    interior_bounds: tuple[int, int, int, int],
    rng: random.Random,
) -> None:
    """Second pass (B4/Q4): place each building its plot couldn't seat
    into any town-wide gap. Services are placed first so they are never
    the dropped ones; a service that still won't fit evicts placed
    residentials until it seats. Residentials that don't fit drop
    silently (count flexes within the size-class band)."""
    service_roles = _service_roles()
    placed = {m.index for plan in all_plans for m in plan.members}
    spilled = [i for i in range(n) if i not in placed]
    spilled.sort(key=lambda i: 0 if roles[i] in service_roles else 1)
    for idx in spilled:
        plan = _ClusterPlan(
            kind="solo",
            members=[_ClusterMember(
                index=idx, role=roles[idx], size=sizes[idx],
                rect=_layout_solo(sizes[idx])[0],
            )],
            bbox=Rect(0, 0, 0, 0),
            interior_links_rolled=[],
        )
        if _try_place_plan(
            plan, occupied, [], interior_bounds, rng, 0, False,
        ):
            occupied.append(plan.bbox)
            all_plans.append(plan)
            continue
        if roles[idx] not in service_roles:
            continue  # residential drops — count flexes in the band
        if not _seat_service_by_eviction(
            plan, all_plans, occupied, roles, interior_bounds, rng,
        ):
            raise RuntimeError(
                f"service role {roles[idx]!r} could not be placed "
                "(no residential cluster left to evict)",
            )


def _seat_service_by_eviction(
    plan: _ClusterPlan,
    all_plans: list[_ClusterPlan],
    occupied: list[Rect],
    roles: list[str],
    interior_bounds: tuple[int, int, int, int],
    rng: random.Random,
) -> bool:
    """Evict the smallest all-residential cluster, retrying the service
    in the freed town-wide space, until it seats or no residential-only
    cluster is left (Q4: residentials yield the slack, services protected)."""
    while True:
        candidates = [
            p for p in all_plans
            if p.members
            and all(roles[m.index] == "residential" for m in p.members)
        ]
        if not candidates:
            return False
        victim = min(candidates, key=lambda p: len(p.members))
        all_plans.remove(victim)
        if victim.bbox in occupied:
            occupied.remove(victim.bbox)
        if _try_place_plan(
            plan, occupied, [], interior_bounds, rng, 0, False,
        ):
            occupied.append(plan.bbox)
            all_plans.append(plan)
            return True

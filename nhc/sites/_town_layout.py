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

import random
from dataclasses import dataclass, field
from itertools import permutations
from typing import TYPE_CHECKING

from nhc.dungeon.model import Rect

if TYPE_CHECKING:
    from nhc.sites.town import _TownSizeConfig


# Service roles imported lazily inside helpers to avoid circular
# import (nhc.sites.town imports this module).


CLUSTER_BBOX_GAP = 2
"""Minimum tiles between two cluster bboxes so a street fits."""

MAX_CLUSTER_MEMBERS = 4
"""Cluster size cap (1..4)."""

MAX_PLACEMENT_ATTEMPTS = 50
"""Per-archetype rejection-sampling attempts before demotion."""

CLUSTER_COUNT_RANGE: dict[str, tuple[int, int]] = {
    "hamlet": (2, 2),
    "village": (2, 3),
    "town": (3, 4),
    "city": (4, 6),
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
    # A few balanced ±1 swaps; clamp to [1, MAX_CLUSTER_MEMBERS].
    swap_attempts = max(2, k)
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
    each other on both axes (i.e. would block a 2-tile street)."""
    dx = max(0, max(a.x - b.x2, b.x - a.x2))
    dy = max(0, max(a.y - b.y2, b.y - a.y2))
    return dx < gap and dy < gap


def _try_place_plan(
    plan: _ClusterPlan,
    placed_bboxes: list[Rect],
    forbidden_rects: list[Rect],
    bounds: tuple[int, int, int, int],
    rng: random.Random,
) -> bool:
    """Search for a valid origin for ``plan``. Random sampling
    first; on exhaustion, fall back to a shuffled deterministic
    scan so any geometrically-valid position is found. Mutates
    ``plan`` on success."""
    min_x, min_y, max_x, max_y = bounds
    rects = [m.rect for m in plan.members]
    cluster_w, cluster_h = _cluster_dims(rects)
    ox_lo, ox_hi = min_x + 1, max_x - cluster_w - 1
    oy_lo, oy_hi = min_y + 1, max_y - cluster_h - 1
    if ox_hi < ox_lo or oy_hi < oy_lo:
        return False

    def _check(ox: int, oy: int) -> bool:
        bbox = _bbox_for((ox, oy), (cluster_w, cluster_h))
        for p in placed_bboxes:
            if _bboxes_overlap_with_gap(bbox, p, CLUSTER_BBOX_GAP):
                return False
        for fr in forbidden_rects:
            if _bboxes_overlap_with_gap(bbox, fr, CLUSTER_BBOX_GAP):
                return False
        return True

    valid_origin: tuple[int, int] | None = None
    for _ in range(MAX_PLACEMENT_ATTEMPTS):
        ox = rng.randint(ox_lo, ox_hi)
        oy = rng.randint(oy_lo, oy_hi)
        if _check(ox, oy):
            valid_origin = (ox, oy)
            break
    if valid_origin is None:
        # Deterministic scan with shuffled order so the result
        # remains seed-dependent and unbiased.
        ox_range = list(range(ox_lo, ox_hi + 1))
        oy_range = list(range(oy_lo, oy_hi + 1))
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
    config: _TownSizeConfig,
    forbidden_rects: list[Rect],
    rng: random.Random,
) -> list[_ClusterPlan]:
    """Place each cluster bbox via rejection sampling. On
    exhaustion, demote the archetype one step and retry. ``solo``
    splits a row/column cluster into per-member solos placed
    independently."""
    placed_bboxes: list[Rect] = list(forbidden_rects)
    out: list[_ClusterPlan] = []
    bounds = (
        0, 0, config.surface_width, config.surface_height,
    )

    for plan in plans:
        success = _try_place_plan(
            plan, placed_bboxes, forbidden_rects, bounds, rng,
        )
        current = plan
        while not success:
            next_kind = _DEMOTE_NEXT.get(current.kind)
            if next_kind is None:
                break
            if next_kind == "split":
                # Solo each member independently.
                solo_plans = _split_into_solos(current, rng)
                for sp in solo_plans:
                    if _try_place_plan(
                        sp, placed_bboxes, forbidden_rects, bounds,
                        rng,
                    ):
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
            success = _try_place_plan(
                current, placed_bboxes, forbidden_rects, bounds, rng,
            )

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
) -> list[_ClusterPlan]:
    """Top-level cluster packer (drop-in replacement for the legacy
    greedy row packer).

    ``roles`` and ``sizes`` are parallel input lists, one per
    building. Returns a list of placed :class:`_ClusterPlan`s
    whose member rects span every input index.
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
    return _place_clusters(plans, config, forbidden_rects, rng)


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

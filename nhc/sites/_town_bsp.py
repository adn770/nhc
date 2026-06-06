"""Shallow BSP partitioner for the town / settlement generator.

Pure geometry, no ``Level`` / surface dependency. Carves the buildable
interior into a few neighbourhood **plots** (leaves = cuts + 1)
separated by reserved street **gutters**, and reserves **big / small
plaza** rects carved *out of* host leaves (not consuming a leaf). The
plot-fill stage (Phase 2) packs buildings into each plot; Phase 4 wires
it into ``assemble_town``.

Design contract: ``design/town_generator.md`` §3.1-§3.2 — shallow
partition (D2), two-tier plazas carved from a leaf (D7, B2), correct
cut/leaf arithmetic (B1), village auto-shrink (Q6), non-palisade
single-plot path (Q2).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from nhc.dungeon.model import Rect
from nhc.sites._town_layout import CLUSTER_BBOX_GAP

# Largest single-building footprint top across ``ARCHETYPE_CONFIG``
# (inn / temple ``size_range`` top = 16). A leaf must hold at least a
# solo cluster of the largest building plus the packing buffer and a
# plot margin, or "a neighbourhood holds several clusters" degrades to
# slivers. This is the *floor*; the leaf-count target drives depth.
_MAX_BUILDING_DIM = 16
_PLOT_MARGIN = 2
MIN_PLOT_DIM = _MAX_BUILDING_DIM + 2 * CLUSTER_BBOX_GAP + _PLOT_MARGIN

# Leaf-count target per size class (leaves = cuts + 1). Hamlet is a
# single plot (no split); the larger classes stay shallow on purpose.
_LEAF_TARGET_RANGE: dict[str, tuple[int, int]] = {
    "hamlet": (1, 1),
    "village": (2, 2),
    "town": (3, 4),
    "city": (4, 6),
}

# Street gutter width reserved at each cut (§3.6): wider lanes for the
# urban tiers, a tight lane for a village.
_GUTTER_WIDTH: dict[str, int] = {
    "hamlet": 1,
    "village": 1,
    "town": 2,
    "city": 2,
}

# Cut position as a fraction of the split side — central enough to
# avoid slivers, random enough that plots vary (§3.1, Q5).
_CUT_BAND = (0.40, 0.60)

# Plaza dims. Big = fountain (village/town 7, city 11); small = well
# (5, every class). Counts per class are in ``_PLAZA_PLAN`` (D7).
_BIG_PLAZA_DIM: dict[str, int] = {"village": 7, "town": 7, "city": 11}
_SMALL_PLAZA_DIM = 5

_PLAZA_PLAN: dict[str, list[str]] = {
    "hamlet": ["small"],
    "village": ["big"],
    "town": ["big", "small"],
    "city": ["big", "small", "small"],
}

# Village big-plaza auto-shrink (Q6): if the host leaf is too tight to
# hold the fountain square *and* retain building room, shrink to 5x5
# (fountain kept). Trigger: host min dim < big dim + this keep-room.
_PLAZA_BUILD_KEEP = 8


@dataclass(frozen=True)
class Plaza:
    """A plaza rect carved out of a host plot. ``tier`` is ``"big"``
    (fountain, civic heart) or ``"small"`` (well, neighbourhood pocket).
    The feature is chosen from the tier at stamp time, so a tier stays
    ``"big"`` even when auto-shrunk to the small dim."""

    rect: Rect
    tier: str


@dataclass
class Plot:
    """A neighbourhood leaf. ``plaza`` is the open square carved out of
    it (a per-plot ``forbidden_rect`` for the packer), or ``None``."""

    rect: Rect
    plaza: Plaza | None = None


@dataclass
class Partition:
    """Result of partitioning the interior: disjoint ``plots`` whose
    union with ``gutters`` tiles the interior exactly."""

    plots: list[Plot]
    gutters: list[Rect]
    size_class: str


def partition_interior(
    interior: Rect,
    size_class: str,
    rng: random.Random,
    *,
    single_plot: bool = False,
) -> Partition:
    """Partition ``interior`` into neighbourhood plots + gutters and
    reserve the size class's plazas.

    ``single_plot`` forces the no-BSP path (hamlet, or any
    ``suppress_palisade`` site — Q2): one plot = the whole interior with
    a single civic plaza reserved inside it.
    """
    if single_plot or size_class not in _LEAF_TARGET_RANGE:
        target = 1
    else:
        target = rng.randint(*_LEAF_TARGET_RANGE[size_class])

    if target <= 1:
        leaves, gutters = [interior], []
    else:
        gutter = _GUTTER_WIDTH.get(size_class, 1)
        leaves, gutters = _split_to_target(interior, target, gutter, rng)

    plots = _reserve_plazas(leaves, size_class, interior, rng, single_plot)
    return Partition(plots=plots, gutters=gutters, size_class=size_class)


def _split_to_target(
    interior: Rect, target: int, gutter: int, rng: random.Random,
) -> tuple[list[Rect], list[Rect]]:
    """Greedily split the largest splittable leaf until ``target``
    leaves exist (or no leaf can split without breaking ``MIN_PLOT_DIM``).
    """
    leaves = [interior]
    gutters: list[Rect] = []
    while len(leaves) < target:
        order = sorted(
            range(len(leaves)),
            key=lambda i: leaves[i].width * leaves[i].height,
            reverse=True,
        )
        for i in order:
            split = _try_split(leaves[i], gutter, rng)
            if split is not None:
                child_a, gutter_rect, child_b = split
                leaves[i] = child_a
                leaves.append(child_b)
                gutters.append(gutter_rect)
                break
        else:
            break  # nothing left to split
    return leaves, gutters


def _try_split(
    rect: Rect, gutter: int, rng: random.Random,
) -> tuple[Rect, Rect, Rect] | None:
    """Split ``rect`` across its longer side, reserving ``gutter`` tiles
    at the cut. Returns ``(child_a, gutter_rect, child_b)`` or ``None``
    if no cut keeps both children at ``MIN_PLOT_DIM``."""
    if rect.width > rect.height:
        vertical = True
    elif rect.height > rect.width:
        vertical = False
    else:
        vertical = rng.random() < 0.5
    span = rect.width if vertical else rect.height

    lo = int(span * _CUT_BAND[0])
    hi = int(span * _CUT_BAND[1])
    cut_min = max(lo, MIN_PLOT_DIM)
    cut_max = min(hi, span - gutter - MIN_PLOT_DIM)
    if cut_min > cut_max:
        return None
    cut = rng.randint(cut_min, cut_max)

    if vertical:
        child_a = Rect(rect.x, rect.y, cut, rect.height)
        gutter_rect = Rect(rect.x + cut, rect.y, gutter, rect.height)
        child_b = Rect(
            rect.x + cut + gutter, rect.y,
            rect.width - cut - gutter, rect.height,
        )
    else:
        child_a = Rect(rect.x, rect.y, rect.width, cut)
        gutter_rect = Rect(rect.x, rect.y + cut, rect.width, gutter)
        child_b = Rect(
            rect.x, rect.y + cut + gutter,
            rect.width, rect.height - cut - gutter,
        )
    return child_a, gutter_rect, child_b


def _reserve_plazas(
    leaves: list[Rect],
    size_class: str,
    interior: Rect,
    rng: random.Random,
    single_plot: bool,
) -> list[Plot]:
    """Carve one plaza rect out of distinct host leaves: the big plaza
    in the most central leaf, small plazas in the most peripheral. A
    wall-less single plot reads fine with one civic feature, so the plan
    is capped to one plaza there."""
    plots = [Plot(rect=leaf) for leaf in leaves]
    plan = list(_PLAZA_PLAN.get(size_class, []))
    if single_plot:
        plan = plan[:1]

    cx, cy = interior.center

    def dist_sq(index: int) -> int:
        px, py = plots[index].rect.center
        return (px - cx) ** 2 + (py - cy) ** 2

    used: set[int] = set()
    for tier in plan:
        # big → most central available leaf; small → most peripheral.
        ranked = sorted(
            range(len(plots)), key=dist_sq, reverse=(tier != "big"),
        )
        host_index = next((i for i in ranked if i not in used), None)
        if host_index is None:
            continue  # fewer leaves than plazas (degenerate tiny site)
        host = plots[host_index]
        dim = _plaza_dim(tier, size_class, host.rect)
        host.plaza = Plaza(
            rect=_place_plaza_in_leaf(host.rect, dim, rng), tier=tier,
        )
        used.add(host_index)
    return plots


def _plaza_dim(tier: str, size_class: str, host: Rect) -> int:
    """Plaza side length. Big plazas auto-shrink to the small dim when
    the host leaf is too tight to keep building room (Q6)."""
    if tier == "small":
        return _SMALL_PLAZA_DIM
    dim = _BIG_PLAZA_DIM[size_class]
    if min(host.width, host.height) < dim + _PLAZA_BUILD_KEEP:
        return _SMALL_PLAZA_DIM
    return dim


def _place_plaza_in_leaf(
    leaf: Rect, dim: int, rng: random.Random,
) -> Rect:
    """Place a ``dim``×``dim`` plaza inside ``leaf``, off-centre
    (rng-jittered, not snapped to the leaf centroid). The dim is clamped
    to the leaf so the plaza always fits."""
    width = min(dim, leaf.width)
    height = min(dim, leaf.height)
    max_x = leaf.x2 - width
    max_y = leaf.y2 - height
    ox = rng.randint(leaf.x, max_x) if max_x > leaf.x else leaf.x
    oy = rng.randint(leaf.y, max_y) if max_y > leaf.y else leaf.y
    return Rect(ox, oy, width, height)

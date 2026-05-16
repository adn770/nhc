"""Builder / regions walk → ``V5OpEntry(V5RoofOp)``.

:func:`emit_roofs` walks ``builder.regions`` for Building regions
and synthesises a ``V5RoofOp`` per building using the same seed /
tint algorithm as
:func:`nhc.rendering.ir_emitter.emit_building_roofs`. Gated on
``ctx.floor_kind == "surface"`` so building-floor / dungeon / cave
IRs skip the layer entirely.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.OpEntry import OpEntryT
from nhc.rendering.ir._fb.RoofOp import RoofOpT
from nhc.rendering.ir._fb.RoofStyle import RoofStyle
from nhc.rendering.ir._fb.RoofTilePattern import RoofTilePattern


# Mirrors :data:`nhc.rendering.ir_emitter._ROOF_TINTS`. Duplicated
# rather than imported so the v5 emit pipeline has no upward
# dependency on the v4 emit module.
_ROOF_TINTS: tuple[str, ...] = (
    "#8A8A8A",
    "#8A7A5A",
    "#8A5A3A",
    "#5A5048",
    "#7A5A3A",
)

_SM64_GOLDEN = 0x9E3779B97F4A7C15
_SM64_C1 = 0xBF58476D1CE4E5B9
_SM64_C2 = 0x94D049BB133111EB
_SM64_MASK = 0xFFFFFFFFFFFFFFFF


def _splitmix64_first(seed: int) -> int:
    state = (seed + _SM64_GOLDEN) & _SM64_MASK
    z = ((state ^ (state >> 30)) * _SM64_C1) & _SM64_MASK
    z = ((z ^ (z >> 27)) * _SM64_C2) & _SM64_MASK
    return z ^ (z >> 31)


def _wrap(roof_op: RoofOpT) -> OpEntryT:
    entry = OpEntryT()
    entry.opType = Op.RoofOp
    entry.op = roof_op
    return entry


def _decode_id(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else (value or "")


def _pick_style(region: Any, building: Any | None = None) -> int:
    """Pick the RoofStyle that matches the legacy shape-driven
    geometry dispatch byte-for-byte, with optional per-building
    overrides.

    The Rust roof painter used to ignore RoofStyle and pick
    Pyramid vs Gable from ``shape_tag`` + bbox dimensions:

    - ``l_shape_*`` → Gable
    - ``rect`` with square bbox → Pyramid; wide / tall → Gable
    - everything else (octagon / circle / unknown) → Pyramid

    Now the painter dispatches per-style, so the emit layer has
    to stamp the corresponding RoofStyle. Producing the same
    style the painter would auto-pick keeps every existing roof
    pixel-identical with the legacy output.

    The ``building`` argument is currently unused for geometry —
    forest watchtowers (``roof_material == "wood"``) used to
    override to the WitchHat cone, but that style was retired, so
    they now take the normal shape-driven pick (their circle /
    octagon footprint → Pyramid). ``roof_material`` still feeds
    the texture overlay via :func:`_pick_sub_pattern`.
    """
    shape_tag = _decode_id(getattr(region, "shapeTag", "") or "")
    if shape_tag.startswith("l_shape"):
        return RoofStyle.Gable
    if shape_tag == "rect":
        outline = getattr(region, "outline", None)
        verts = getattr(outline, "vertices", None) if outline else None
        if verts:
            xs = [float(v.x) for v in verts]
            ys = [float(v.y) for v in verts]
            w = max(xs) - min(xs)
            h = max(ys) - min(ys)
            if abs(w - h) < 1e-6:
                return RoofStyle.Pyramid
            return RoofStyle.Gable
        return RoofStyle.Pyramid
    return RoofStyle.Pyramid


# wall_material → tile-pattern overlay. Brick / stone / dungeon
# all fall through to the Shingle default (the organic running-
# bond that replaced the geometry-baked gable shingles), so
# default-biome towns keep the organic rooftop look. Adobe
# (drylands towns) and wood walls (marsh towns) both opt into
# Thatch — the rural straw overlay — so they stay distinct from
# the Shingle default. (Pantile was retired.)
_WALL_MATERIAL_TO_PATTERN: dict[str, int] = {
    "adobe": RoofTilePattern.Thatch,
    "wood": RoofTilePattern.Thatch,
}


# Semantic roof_material → pattern. Generators set this on a
# Building when they want an explicit roof texture independent
# of the wall material — e.g. a stone-walled mansion with a
# slate roof, or a brick cottage with thatch on top. The
# mapping wins over the wall_material fallback. ``"wood"`` (set
# on forest watchtowers) intentionally has no entry — it falls
# through to the wall_material default so the wooden cap is not
# overlaid with a competing explicit tile texture.
_ROOF_MATERIAL_TO_PATTERN: dict[str, int] = {
    "thatch": RoofTilePattern.Thatch,
    "tile": RoofTilePattern.Thatch,
    "slate": RoofTilePattern.Slate,
    "fishscale": RoofTilePattern.Fishscale,
    "staggered": RoofTilePattern.Staggered,
}


def _pick_sub_pattern(building: Any | None) -> int:
    """Pick the RoofTilePattern overlay for a building.

    Resolution order:
    1. If ``Building.roof_material`` matches a semantic key
       (``"thatch"`` / ``"tile"`` / ``"slate"`` / ``"fishscale"``)
       use the explicit pattern. ``"wood"`` (forest watchtowers)
       has no entry and falls through here.
    2. Otherwise fall back to ``wall_material``: ``adobe``
       (drylands biome) and ``wood`` (marsh biome) → Thatch.
    3. Default biome materials (brick / stone / dungeon) and any
       unknown material map to Shingle — the organic running-bond
       default that replaced the old geometry-baked gable
       shingles, so ordinary towns keep the organic rooftop look.
    """
    if building is None:
        return RoofTilePattern.Shingle
    roof_material = getattr(building, "roof_material", None) or ""
    explicit = _ROOF_MATERIAL_TO_PATTERN.get(roof_material)
    if explicit is not None:
        return explicit
    wall_material = getattr(building, "wall_material", None) or ""
    return _WALL_MATERIAL_TO_PATTERN.get(
        wall_material, RoofTilePattern.Shingle,
    )


def emit_roofs(builder: Any) -> list[OpEntryT]:
    """Walk builder.regions for Building regions and emit V5RoofOps.

    Gate: only fire on surface IRs (``ctx.floor_kind == "surface"``).
    Building-floor IRs and dungeon / cave / non-site IRs skip the
    layer entirely — matches :func:`emit_site_overlays` running
    :func:`emit_building_roofs` only for the site surface, and
    :func:`emit_building_overlays` not running it for individual
    building floors.

    When ``builder.site`` is set (the canonical site-surface
    path), each ``building.{i}`` Region correlates with
    ``site.buildings[i]`` so :func:`_pick_style` and
    :func:`_pick_sub_pattern` can read per-Building hints
    (``roof_material`` / ``wall_material``) for geometry +
    overlay overrides. Synthetic / test buffers without a Site
    fall through to the shape-only style picker and Shingle
    overlay default.
    """
    if getattr(builder.ctx, "floor_kind", "") != "surface":
        return []

    site = getattr(builder, "site", None)
    buildings = list(getattr(site, "buildings", None) or [])

    base_seed = builder.ctx.seed
    result: list[OpEntryT] = []
    for region in builder.regions:
        rid = _decode_id(getattr(region, "id", ""))
        if not rid.startswith("building."):
            continue
        try:
            i = int(rid.split(".", 1)[1])
        except ValueError:
            continue
        building = buildings[i] if 0 <= i < len(buildings) else None
        rng_seed = (base_seed + 0xCAFE + i) & _SM64_MASK
        tint_seed = (rng_seed ^ 0xC0FFEE) & _SM64_MASK
        tint = _ROOF_TINTS[_splitmix64_first(tint_seed) % len(_ROOF_TINTS)]
        v5 = RoofOpT()
        v5.regionRef = f"building.{i}"
        v5.style = _pick_style(region, building)
        v5.tone = 1
        v5.tint = tint
        v5.seed = rng_seed
        v5.subPattern = _pick_sub_pattern(building)
        result.append(_wrap(v5))
    return result



"""Generator-driven samples — wrap the production world / dungeon
generators so each sample exercises the full IR pipeline.

Used to surface integration bugs that pure synthetic samples miss:
generator-induced layouts, real RNG sequences, real wall-emit
patterns, real corridor connectivity.

Each builder returns a :class:`BuildResult` carrying both the IR
buffer and the source ``Level`` (and ``Site`` when relevant) so
the optional ``--labels`` overlay can extract room / corridor /
door metadata.
"""

from __future__ import annotations

import random as _stdrandom

from nhc.rendering.ir_emitter import build_floor_ir

from ._core import BuildResult, CATALOG, SampleSpec


# ── BSP shape-variety sweep ────────────────────────────────────────


def _build_bsp(
    seed: int, *, shape_variety: float, theme: str,
) -> BuildResult:
    from nhc.dungeon.generator import GenerationParams
    from nhc.dungeon.generators.bsp import BSPGenerator

    params = GenerationParams(
        seed=seed,
        shape_variety=shape_variety,
        theme=theme,
    )
    level = BSPGenerator().generate(params)
    buf = build_floor_ir(level, seed=seed)
    return BuildResult(buf=buf, level=level)


# ── Structural templates ───────────────────────────────────────────


def _build_template(
    seed: int, *, template: str, w: int, h: int,
) -> BuildResult:
    from nhc.dungeon.generator import GenerationParams
    from nhc.dungeon.pipeline import generate_level as gen_level

    params = GenerationParams(
        width=w, height=h, depth=1, seed=seed,
        shape_variety=0.5, template=template,
    )
    level = gen_level(params)
    buf = build_floor_ir(level, seed=seed)
    return BuildResult(buf=buf, level=level)


# ── Underworld biomes ──────────────────────────────────────────────


def _build_underworld(
    seed: int, *, theme: str, w: int, h: int,
) -> BuildResult:
    from nhc.dungeon.generator import GenerationParams
    from nhc.dungeon.pipeline import generate_level as gen_level

    params = GenerationParams(
        width=w, height=h, depth=1, seed=seed,
        shape_variety=0.3, theme=theme,
    )
    level = gen_level(params)
    buf = build_floor_ir(level, seed=seed)
    return BuildResult(buf=buf, level=level)


# ── Settlements (town surface at each size class) ──────────────────


def _build_settlement(seed: int, *, size_class: str) -> BuildResult:
    from nhc.sites.town import assemble_town

    site = assemble_town(
        f"settlement_{size_class}_seed{seed}",
        _stdrandom.Random(seed),
        size_class=size_class,
    )
    buf = build_floor_ir(site.surface, seed=seed, site=site)
    return BuildResult(buf=buf, level=site.surface, site=site)


# ── Sites (macro: surface for each kind) ───────────────────────────


def _build_site_surface(seed: int, *, kind: str) -> BuildResult:
    from nhc.sites._site import assemble_site

    site = assemble_site(kind, f"site_{kind}_seed{seed}", _stdrandom.Random(seed))
    buf = build_floor_ir(site.surface, seed=seed, site=site)
    return BuildResult(buf=buf, level=site.surface, site=site)


# ── Catalog ────────────────────────────────────────────────────────


def _seed_only(**extra) -> dict:
    """Helper to keep params dicts compact in the SampleSpec table."""
    return extra


CATALOG.extend([
    SampleSpec(
        name="bsp_rect",
        category="generators/dungeon",
        description="BSP-generated dungeon with rectangular rooms only.",
        params=_seed_only(generator="bsp", shape_variety=0.0, theme="dungeon"),
        build=lambda s: _build_bsp(s, shape_variety=0.0, theme="dungeon"),
    ),
    SampleSpec(
        name="bsp_mixed",
        category="generators/dungeon",
        description="BSP-generated dungeon mixing rect + smooth-shape rooms.",
        params=_seed_only(generator="bsp", shape_variety=0.5, theme="dungeon"),
        build=lambda s: _build_bsp(s, shape_variety=0.5, theme="dungeon"),
    ),
    SampleSpec(
        name="bsp_shapes",
        category="generators/dungeon",
        description="BSP-generated dungeon with smooth shapes preferred.",
        params=_seed_only(generator="bsp", shape_variety=1.0, theme="dungeon"),
        build=lambda s: _build_bsp(s, shape_variety=1.0, theme="dungeon"),
    ),
])

for _label, _template, _w, _h in [
    ("tower", "procedural:tower", 60, 40),
    ("crypt", "procedural:crypt", 80, 40),
    ("mine",  "procedural:mine",  80, 40),
]:
    # Bind loop vars at definition time; lambda default args pin them.
    CATALOG.append(SampleSpec(
        name=_label,
        category="generators/templates",
        description=f"{_label} template generator at default shape_variety.",
        params=_seed_only(generator=_template, w=_w, h=_h),
        build=(lambda s, t=_template, w=_w, h=_h:
               _build_template(s, template=t, w=w, h=h)),
    ))

for _label, _theme, _w, _h in [
    ("cave",             "cave",              80, 50),
    ("fungal_cavern",    "fungal_cavern",     90, 55),
    ("lava_chamber",     "lava_chamber",     100, 60),
    ("underground_lake", "underground_lake", 110, 65),
]:
    CATALOG.append(SampleSpec(
        name=_label,
        category="generators/underworld",
        description=f"{_label} underworld biome at shape_variety=0.3.",
        params=_seed_only(theme=_theme, w=_w, h=_h),
        build=(lambda s, t=_theme, w=_w, h=_h:
               _build_underworld(s, theme=t, w=w, h=h)),
    ))

for _size in ("hamlet", "village", "town", "city"):
    CATALOG.append(SampleSpec(
        name=_size,
        category="generators/settlements",
        description=f"Town surface at {_size} size class.",
        params=_seed_only(size_class=_size, generator="assemble_town"),
        build=(lambda s, sc=_size: _build_settlement(s, size_class=sc)),
    ))

# Sites: macro surface for each kind (skip "town" — covered by
# the settlements category at all four sizes).
for _kind in (
    "tower", "farm", "mansion", "keep", "temple",
    "cottage", "ruin", "mage_residence",
):
    CATALOG.append(SampleSpec(
        name=_kind,
        category="generators/sites/macro",
        description=f"{_kind} site surface (macro view).",
        params=_seed_only(kind=_kind, generator="assemble_site"),
        build=(lambda s, k=_kind: _build_site_surface(s, kind=k)),
    ))


__all__ = []  # All exports go through CATALOG at module-load time.

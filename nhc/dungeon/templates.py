"""Structural templates for dungeon generation.

A StructuralTemplate is a data-driven composition layer over
the existing BSP and cellular generators. It controls room
shapes, sizes, layout strategy, and post-generation transforms
without changing the core generation algorithms.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from nhc.dungeon.generator import GenerationParams, Range


@dataclass
class StructuralTemplate:
    """Data-driven dungeon structure definition."""

    name: str
    base_generator: str          # "bsp" or "cellular"
    preferred_shapes: list[str]
    shape_weights: list[float] | None = None
    room_size_override: Range | None = None
    room_count_override: Range | None = None
    layout_strategy: str = "default"
    forced_connectivity: float | None = None
    transforms: list[str] = field(default_factory=list)
    theme: str = "dungeon"
    entity_pool_override: str | None = None


# ── Template registry ──────────────────────────────────────────

TEMPLATES: dict[str, StructuralTemplate] = {
    "procedural:tower": StructuralTemplate(
        name="procedural:tower",
        base_generator="bsp",
        preferred_shapes=["circle", "octagon"],
        layout_strategy="radial",
        room_size_override=Range(4, 7),
    ),
    "procedural:keep": StructuralTemplate(
        name="procedural:keep",
        base_generator="bsp",
        preferred_shapes=["rect", "octagon"],
        layout_strategy="walled",
        transforms=["add_battlements", "add_gate"],
    ),
    "procedural:crypt": StructuralTemplate(
        name="procedural:crypt",
        base_generator="bsp",
        preferred_shapes=["rect", "pill"],
        room_size_override=Range(3, 6),
        forced_connectivity=0.3,
        theme="crypt",
        transforms=["narrow_corridors"],
    ),
    "procedural:mine": StructuralTemplate(
        name="procedural:mine",
        base_generator="bsp",
        preferred_shapes=["rect"],
        layout_strategy="linear",
        theme="mine",
        transforms=["add_cart_tracks", "add_ore_deposits"],
    ),
}


def apply_template(
    params: GenerationParams,
    template: StructuralTemplate,
) -> GenerationParams:
    """Apply a template's overrides to generation params.

    Returns a new GenerationParams with template-specific values
    applied. The original params are not modified.
    """
    effective = copy.copy(params)
    effective.template = template.name

    if template.room_size_override is not None:
        effective.room_size = Range(
            template.room_size_override.min,
            template.room_size_override.max,
        )

    if template.room_count_override is not None:
        effective.room_count = Range(
            template.room_count_override.min,
            template.room_count_override.max,
        )

    if template.forced_connectivity is not None:
        effective.connectivity = template.forced_connectivity

    if template.theme != "dungeon":
        effective.theme = template.theme

    if template.preferred_shapes:
        effective.preferred_shapes = list(template.preferred_shapes)

    if template.layout_strategy != "default":
        effective.layout_strategy = template.layout_strategy

    return effective

"""YAML loader for hexcrawl content packs.

A pack lives under ``content/<id>/`` with at least:

* ``pack.yaml`` -- the manifest loaded here.
* ``locale_keys.yaml`` -- optional sibling listing required i18n keys.

The loader is intentionally strict: unknown generators, unknown
biomes in cost overrides, non-positive numbers, and inverted feature
targets are all rejected with :class:`PackValidationError` so that
content authoring problems surface early rather than at first play.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from nhc.hexcrawl.model import Biome


# ---------------------------------------------------------------------------
# Defaults (also used by the hex engine when no pack override is given)
# ---------------------------------------------------------------------------


DEFAULT_BIOME_COSTS: dict[Biome, int] = {
    Biome.GREENLANDS: 1,
    Biome.DRYLANDS: 1,
    Biome.SANDLANDS: 2,
    Biome.ICELANDS: 2,
    Biome.FOREST: 2,
    Biome.MOUNTAIN: 4,
    Biome.DEADLANDS: 2,
    # Hills ~= forest cost; wetlands cost more -- marsh + swamp
    # are slow slogs, tuned between forest (2) and mountain (4).
    Biome.HILLS: 2,
    Biome.MARSH: 3,
    Biome.SWAMP: 3,
    # Open water is impassable on foot in v1. Cost 99 so the
    # player routes around it (future: boats / swimming).
    Biome.WATER: 99,
}


KNOWN_GENERATORS: frozenset[str] = frozenset({
    "bsp_regions",
    # M-G.4: elevation + moisture simplex fields, Whittaker-
    # style biome lookup. Same HexWorld output shape as BSP;
    # the dispatcher in Game._init_hex_world picks which one
    # to call.
    "perlin_regions",
})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PackValidationError(ValueError):
    """Raised when a pack manifest fails validation."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MapParams:
    generator: str
    width: int
    height: int
    # BSP-specific knobs; ignored when generator is perlin_regions.
    num_regions: int = 5
    region_min: int = 6
    region_max: int = 16
    # Perlin-specific knobs; ignored when generator is
    # bsp_regions. Defaults tuned for the 25x16 testland-perlin
    # shape -- smaller elevation_scale = larger continents.
    elevation_scale: float = 0.08
    moisture_scale: float = 0.12
    octaves: int = 4


@dataclass
class FeatureTarget:
    min: int
    max: int


@dataclass
class FeatureTargets:
    hub: int = 1
    village: FeatureTarget = field(
        default_factory=lambda: FeatureTarget(1, 2)
    )
    dungeon: FeatureTarget = field(
        default_factory=lambda: FeatureTarget(3, 5)
    )
    wonder: FeatureTarget = field(
        default_factory=lambda: FeatureTarget(1, 3)
    )


@dataclass
class PackMeta:
    id: str
    version: int
    attribution: str
    map: MapParams
    features: FeatureTargets
    biome_costs: dict[Biome, int]
    locale_keys: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_pack(path: Path) -> PackMeta:
    """Load and validate a pack manifest from ``pack.yaml``.

    Raises :class:`FileNotFoundError` if the manifest is missing,
    :class:`PackValidationError` for any schema problem.
    """
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise PackValidationError("pack.yaml must be a mapping")

    pack_id = _require(raw, "id", str)
    version = int(raw.get("version", 0))
    attribution = str(raw.get("attribution", ""))

    map_params = _parse_map(raw)
    features = _parse_features(raw.get("features"))
    biome_costs = _parse_biome_costs(raw.get("biome_costs"))
    locale_keys = _load_locale_keys(path.parent)

    return PackMeta(
        id=pack_id,
        version=version,
        attribution=attribution,
        map=map_params,
        features=features,
        biome_costs=biome_costs,
        locale_keys=locale_keys,
    )


# ---------------------------------------------------------------------------
# Internal parsers
# ---------------------------------------------------------------------------


def _require(d: dict[str, Any], key: str, ty: type) -> Any:
    if key not in d:
        raise PackValidationError(f"missing required field: {key}")
    val = d[key]
    if not isinstance(val, ty):
        raise PackValidationError(
            f"field {key!r} must be {ty.__name__}, got {type(val).__name__}"
        )
    return val


def _parse_map(raw: dict[str, Any]) -> MapParams:
    block = _require(raw, "map", dict)
    generator = _require(block, "generator", str)
    if generator not in KNOWN_GENERATORS:
        raise PackValidationError(
            f"unknown map generator {generator!r}; "
            f"known: {sorted(KNOWN_GENERATORS)}"
        )
    width = int(_require(block, "width", int))
    height = int(_require(block, "height", int))
    if width <= 0:
        raise PackValidationError(f"map.width must be > 0, got {width}")
    if height <= 0:
        raise PackValidationError(f"map.height must be > 0, got {height}")
    return MapParams(
        generator=generator,
        width=width,
        height=height,
        num_regions=int(block.get("num_regions", 5)),
        region_min=int(block.get("region_min", 6)),
        region_max=int(block.get("region_max", 16)),
        elevation_scale=float(block.get("elevation_scale", 0.08)),
        moisture_scale=float(block.get("moisture_scale", 0.12)),
        octaves=int(block.get("octaves", 4)),
    )


def _parse_features(block: dict[str, Any] | None) -> FeatureTargets:
    if block is None:
        return FeatureTargets()
    out = FeatureTargets()
    if "hub" in block:
        out.hub = int(block["hub"])
    for name in ("village", "dungeon", "wonder"):
        if name in block:
            setattr(out, name, _parse_target(block[name], name))
    return out


def _parse_target(raw: Any, name: str) -> FeatureTarget:
    if not isinstance(raw, dict):
        raise PackValidationError(
            f"features.{name} must be a mapping with min/max"
        )
    if "min" not in raw or "max" not in raw:
        raise PackValidationError(
            f"features.{name} must have both min and max"
        )
    lo = int(raw["min"])
    hi = int(raw["max"])
    if lo > hi:
        raise PackValidationError(
            f"features.{name}: min ({lo}) must be <= max ({hi})"
        )
    return FeatureTarget(lo, hi)


def _parse_biome_costs(block: dict[str, Any] | None) -> dict[Biome, int]:
    out = dict(DEFAULT_BIOME_COSTS)
    if block is None:
        return out
    for name, cost in block.items():
        try:
            biome = Biome(name)
        except ValueError as exc:
            raise PackValidationError(
                f"biome_costs: unknown biome {name!r}"
            ) from exc
        cost_int = int(cost)
        if cost_int <= 0:
            raise PackValidationError(
                f"biome_costs[{name}]: cost must be > 0, got {cost_int}"
            )
        out[biome] = cost_int
    return out


def _load_locale_keys(pack_dir: Path) -> list[str]:
    sibling = pack_dir / "locale_keys.yaml"
    if not sibling.is_file():
        return []
    raw = yaml.safe_load(sibling.read_text()) or {}
    if not isinstance(raw, dict):
        return []
    keys = raw.get("keys", [])
    if not isinstance(keys, list):
        return []
    return [str(k) for k in keys]

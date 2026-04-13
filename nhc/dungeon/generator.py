"""Procedural dungeon generation interface."""

from __future__ import annotations

import abc
import random
from dataclasses import dataclass, field

from nhc.dungeon.model import Level


@dataclass
class Range:
    """Min/max integer range."""
    min: int
    max: int


@dataclass
class GenerationParams:
    """Parameters controlling procedural level generation."""
    width: int = 120
    height: int = 40
    depth: int = 1
    room_count: Range = field(default_factory=lambda: Range(5, 15))
    room_size: Range = field(default_factory=lambda: Range(4, 12))
    corridor_style: str = "straight"  # straight, bent, organic
    density: float = 0.4
    connectivity: float = 0.8
    theme: str = "dungeon"
    seed: int | None = None
    dead_ends: bool = True
    secret_doors: float = 0.1
    water_features: bool = False
    multiple_stairs: bool = False
    shape_variety: float = 0.0  # 0.0 = all rect, 1.0 = all non-rect

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "width": self.width,
            "height": self.height,
            "depth": self.depth,
            "room_count": {"min": self.room_count.min,
                           "max": self.room_count.max},
            "room_size": {"min": self.room_size.min,
                          "max": self.room_size.max},
            "corridor_style": self.corridor_style,
            "density": self.density,
            "connectivity": self.connectivity,
            "theme": self.theme,
            "seed": self.seed,
            "dead_ends": self.dead_ends,
            "secret_doors": self.secret_doors,
            "water_features": self.water_features,
            "multiple_stairs": self.multiple_stairs,
            "shape_variety": self.shape_variety,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GenerationParams":
        """Deserialize from a dictionary, ignoring unknown keys."""
        import dataclasses
        valid_keys = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        if isinstance(filtered.get("room_count"), dict):
            filtered["room_count"] = Range(**filtered["room_count"])
        if isinstance(filtered.get("room_size"), dict):
            filtered["room_size"] = Range(**filtered["room_size"])
        return cls(**filtered)


# ── Map size selection ──────────────────────────────────────────

MAP_SIZES: list[tuple[int, int]] = [
    (40, 40),
    (80, 40),
    (120, 40),
]

# Weights: small and medium are more likely than large
MAP_SIZE_WEIGHTS: list[float] = [0.35, 0.45, 0.20]


def pick_map_size(
    rng: random.Random, depth: int | None = None,
) -> tuple[int, int]:
    """Choose a map size weighted toward smaller dungeons.

    Depth 2 always returns the largest size: the temple sanctuary
    needs a 7x7 odd-dim room to host a TempleShape, and small or
    medium maps sometimes can't produce one (forcing a noisy resize
    fallback).  A guaranteed large map keeps the geometry clean.
    """
    if depth == 2:
        return MAP_SIZES[-1]
    return rng.choices(MAP_SIZES, weights=MAP_SIZE_WEIGHTS, k=1)[0]


class DungeonGenerator(abc.ABC):
    """Abstract base for dungeon generators."""

    @abc.abstractmethod
    def generate(
        self, params: GenerationParams,
        rng: random.Random | None = None,
    ) -> Level:
        """Generate a dungeon level from parameters."""

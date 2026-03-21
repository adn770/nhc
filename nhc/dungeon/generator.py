"""Procedural dungeon generation interface."""

from __future__ import annotations

import abc
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
    width: int = 80
    height: int = 50
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


class DungeonGenerator(abc.ABC):
    """Abstract base for dungeon generators."""

    @abc.abstractmethod
    def generate(self, params: GenerationParams) -> Level:
        """Generate a dungeon level from parameters."""

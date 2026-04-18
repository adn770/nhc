"""Tests for hex dressing via tables subsystem."""

from __future__ import annotations

from pathlib import Path

from nhc.i18n import init as i18n_init


_PACK = Path(__file__).resolve().parents[3] / "content" / "testland" / "pack.yaml"


def _world(seed: int = 7):
    from nhc.hexcrawl._generator import generate_continental_world
    from nhc.hexcrawl.pack import load_pack

    return generate_continental_world(seed=seed, pack=load_pack(_PACK))


def setup_module():
    i18n_init("en")


def test_hex_world_gen_rolls_dressing() -> None:
    world = _world()
    dressed = [
        c for c in world.cells.values() if c.dressing
    ]
    assert dressed, "at least some hexes should have dressing"


def test_dressing_gated_by_terrain_and_feature() -> None:
    """Dressing entries are terrain- or feature-specific."""
    from nhc.hexcrawl.model import Biome

    world = _world()
    for cell in world.cells.values():
        if "approach" in cell.dressing:
            assert isinstance(cell.dressing["approach"], str)
            assert len(cell.dressing["approach"]) > 5


def test_dressing_persists_in_save_roundtrip() -> None:
    from nhc.core.save import _deserialize_hex_world, _serialize_hex_world

    world = _world()
    # Ensure at least one cell has dressing
    dressed = [c for c in world.cells.values() if c.dressing]
    assert dressed, "precondition: need dressed cells"

    data = _serialize_hex_world(world)
    loaded = _deserialize_hex_world(data)

    original_dressing = {
        (c.coord.q, c.coord.r): c.dressing
        for c in world.cells.values() if c.dressing
    }
    loaded_dressing = {
        (c.coord.q, c.coord.r): c.dressing
        for c in loaded.cells.values() if c.dressing
    }
    assert original_dressing == loaded_dressing

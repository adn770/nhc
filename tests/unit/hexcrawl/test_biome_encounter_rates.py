"""Per-biome encounter rates tune wilderness danger.

Today the auto-roll uses a flat 20%; that's boring. Rates now
come from a biome-keyed table so mountain / deadlands feel more
hostile than greenlands / drylands. The constant is exposed for
pack-level tuning down the road.
"""

from __future__ import annotations

from nhc.hexcrawl.encounter_pipeline import (
    BIOME_ENCOUNTER_RATES,
    DEFAULT_ENCOUNTER_RATE,
    rate_for_biome,
)
from nhc.hexcrawl.model import Biome


def test_all_biomes_have_a_configured_rate() -> None:
    for biome in Biome:
        assert biome in BIOME_ENCOUNTER_RATES, (
            f"Biome {biome!r} missing from encounter rate table"
        )


def test_mountain_is_more_dangerous_than_greenlands() -> None:
    assert (
        BIOME_ENCOUNTER_RATES[Biome.MOUNTAIN]
        > BIOME_ENCOUNTER_RATES[Biome.GREENLANDS]
    )


def test_deadlands_is_more_dangerous_than_drylands() -> None:
    assert (
        BIOME_ENCOUNTER_RATES[Biome.DEADLANDS]
        > BIOME_ENCOUNTER_RATES[Biome.DRYLANDS]
    )


def test_rate_for_biome_returns_biome_value() -> None:
    assert rate_for_biome(Biome.MOUNTAIN) == (
        BIOME_ENCOUNTER_RATES[Biome.MOUNTAIN]
    )


def test_rate_for_biome_accepts_override_table() -> None:
    """Packs can pass their own rate dict through rate_for_biome
    without mutating the shared defaults."""
    override = {Biome.FOREST: 0.95}
    assert rate_for_biome(Biome.FOREST, override) == 0.95
    # Missing biomes fall through to the default.
    assert rate_for_biome(Biome.MOUNTAIN, override) == (
        BIOME_ENCOUNTER_RATES[Biome.MOUNTAIN]
    )


def test_default_rate_constant_retained_for_fallback() -> None:
    """DEFAULT_ENCOUNTER_RATE still serves as the final fallback
    for biomes missing from every table."""
    assert 0.0 <= DEFAULT_ENCOUNTER_RATE <= 1.0

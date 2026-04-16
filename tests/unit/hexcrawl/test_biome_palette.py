"""Biome palette expansion (M-G.1).

Three new biomes land in preparation for the noise-based
generator and the Blackmarsh content pack:

* HILLS -- transitional between mountain and lowlands
* MARSH -- shallow, grassy wetland (reptiles, undead light)
* SWAMP -- dense, forested wetland (undead heavy)

Every downstream table that keys off :class:`Biome` must grow
entries for them: pack cost table, encounter pool, per-step
encounter rate, terminal glyph, and the i18n biome labels.
"""

from __future__ import annotations

from nhc.hexcrawl.encounter import DEFAULT_BIOME_POOLS
from nhc.hexcrawl.encounter_pipeline import BIOME_ENCOUNTER_RATES
from nhc.hexcrawl.model import Biome
from nhc.hexcrawl.pack import DEFAULT_BIOME_COSTS
from nhc.i18n import init as i18n_init, t
from nhc.rendering.terminal.hex_renderer import BIOME_GLYPH


_NEW_BIOMES = (Biome.HILLS, Biome.MARSH, Biome.SWAMP)


# ---------------------------------------------------------------------------
# Enum membership
# ---------------------------------------------------------------------------


def test_hills_marsh_swamp_added_to_biome_enum() -> None:
    assert Biome.HILLS.value == "hills"
    assert Biome.MARSH.value == "marsh"
    assert Biome.SWAMP.value == "swamp"


# ---------------------------------------------------------------------------
# Downstream tables
# ---------------------------------------------------------------------------


def test_default_biome_costs_cover_new_biomes() -> None:
    for b in _NEW_BIOMES:
        assert b in DEFAULT_BIOME_COSTS, (
            f"DEFAULT_BIOME_COSTS missing {b!r}"
        )
        # Hills is hill-walking cost; marsh/swamp are wetland
        # slog. All of them are > 1 so they're at least as
        # costly as greenlands.
        assert DEFAULT_BIOME_COSTS[b] >= 2


def test_encounter_pools_cover_new_biomes() -> None:
    for b in _NEW_BIOMES:
        assert b in DEFAULT_BIOME_POOLS, (
            f"DEFAULT_BIOME_POOLS missing {b!r}"
        )
        assert DEFAULT_BIOME_POOLS[b], (
            f"pool for {b!r} must not be empty"
        )


def test_encounter_rates_cover_new_biomes() -> None:
    for b in _NEW_BIOMES:
        assert b in BIOME_ENCOUNTER_RATES, (
            f"BIOME_ENCOUNTER_RATES missing {b!r}"
        )
        rate = BIOME_ENCOUNTER_RATES[b]
        assert 0.0 < rate <= 1.0


def test_wetlands_are_more_dangerous_than_greenlands() -> None:
    """Marsh / swamp should feel hostile; hills sit between
    plains and mountain on the danger dial."""
    gl = BIOME_ENCOUNTER_RATES[Biome.GREENLANDS]
    assert BIOME_ENCOUNTER_RATES[Biome.MARSH] > gl
    assert BIOME_ENCOUNTER_RATES[Biome.SWAMP] > gl
    assert BIOME_ENCOUNTER_RATES[Biome.HILLS] > gl
    # Swamp edges out marsh -- dense cover + undead heavier.
    assert (
        BIOME_ENCOUNTER_RATES[Biome.SWAMP]
        >= BIOME_ENCOUNTER_RATES[Biome.MARSH]
    )


def test_terminal_renderer_has_glyphs_for_new_biomes() -> None:
    for b in _NEW_BIOMES:
        assert b in BIOME_GLYPH, f"BIOME_GLYPH missing {b!r}"
        assert len(BIOME_GLYPH[b]) == 1


def test_terminal_glyphs_are_distinct() -> None:
    """Avoid glyph collisions with existing biomes."""
    glyphs = list(BIOME_GLYPH.values())
    assert len(glyphs) == len(set(glyphs)), (
        f"BIOME_GLYPH has duplicate glyphs: {glyphs}"
    )


# ---------------------------------------------------------------------------
# Locale strings
# ---------------------------------------------------------------------------


def test_biome_labels_exist_in_en_ca_es() -> None:
    for lang in ("en", "ca", "es"):
        i18n_init(lang)
        for b in _NEW_BIOMES:
            key = f"hex.biome.{b.value}"
            label = t(key)
            assert label and not label.startswith("hex."), (
                f"{lang}: key {key!r} not translated "
                f"(got {label!r})"
            )


# ---------------------------------------------------------------------------
# Save-schema round trip
# ---------------------------------------------------------------------------


def test_hexcell_with_new_biome_round_trips_through_save(tmp_path) -> None:
    """Confirm the new biome values survive the autosave pickle.

    The schema is generic over the Biome enum so this should Just
    Work; we pin it with a test because adding enum values is a
    classic silent-breakage class elsewhere in the project.
    """
    import pickle
    from nhc.hexcrawl.coords import HexCoord
    from nhc.hexcrawl.model import HexCell, HexFeatureType

    cell = HexCell(
        coord=HexCoord(q=1, r=1),
        biome=Biome.MARSH,
        feature=HexFeatureType.NONE,
    )
    restored = pickle.loads(pickle.dumps(cell))
    assert restored.biome is Biome.MARSH

"""Integration tests for the bundled testland content pack and
the hex-related i18n keys in the three locale files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nhc.hexcrawl.generator import generate_test_world
from nhc.hexcrawl.model import Biome, HexFeatureType
from nhc.hexcrawl.pack import FeatureTarget, load_pack
from nhc.i18n.manager import TranslationManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _pack_path() -> Path:
    return _project_root() / "content" / "testland" / "pack.yaml"


# ---------------------------------------------------------------------------
# Pack file
# ---------------------------------------------------------------------------


def test_testland_pack_loads_via_loader() -> None:
    pack = load_pack(_pack_path())
    assert pack.id == "testland"
    assert pack.version >= 1
    assert pack.map.generator == "bsp_regions"
    assert pack.map.width == 8
    assert pack.map.height == 8
    assert pack.features.hub == 1
    assert pack.features.village == FeatureTarget(1, 2)
    assert pack.features.dungeon == FeatureTarget(3, 5)
    assert pack.features.wonder == FeatureTarget(1, 3)


def test_testland_locale_keys_file_populated() -> None:
    pack = load_pack(_pack_path())
    # Expected to include at least the pack name and the hub name
    # so the generator can attach meaningful name_keys on cells.
    assert "content.testland.pack.name" in pack.locale_keys
    assert "content.testland.hex.hub.name" in pack.locale_keys


# ---------------------------------------------------------------------------
# Generator via the real pack
# ---------------------------------------------------------------------------


def test_testland_generator_produces_valid_world() -> None:
    pack = load_pack(_pack_path())
    world = generate_test_world(seed=42, pack=pack)
    # 8 x 8 = 64 cells
    assert len(world.cells) == 64
    # Exactly one hub
    hubs = [
        c for c, cell in world.cells.items()
        if cell.feature is HexFeatureType.CITY
    ]
    assert len(hubs) == 1
    # last_hub is set to that hex
    assert world.last_hub == hubs[0]
    # Generator-assigned biome palette must include the essentials
    biomes_present = {cell.biome for cell in world.cells.values()}
    assert Biome.GREENLANDS in biomes_present
    assert Biome.MOUNTAIN in biomes_present
    assert Biome.FOREST in biomes_present
    assert Biome.ICELANDS in biomes_present


# ---------------------------------------------------------------------------
# Locale coverage (EN / CA / ES)
# ---------------------------------------------------------------------------


_REQUIRED_KEYS: tuple[str, ...] = (
    # Engine-level hex strings.
    "hex.ui.day",
    "hex.biome.greenlands",
    "hex.biome.drylands",
    "hex.biome.sandlands",
    "hex.biome.icelands",
    "hex.biome.deadlands",
    "hex.biome.forest",
    "hex.biome.mountain",
    "hex.time.morning",
    "hex.time.midday",
    "hex.time.evening",
    "hex.time.night",
    # Testland-specific strings.
    "content.testland.pack.name",
    "content.testland.hex.hub.name",
    "content.testland.hex.hub.description",
)


@pytest.mark.parametrize("lang", ["en", "ca", "es"])
@pytest.mark.parametrize("key", _REQUIRED_KEYS)
def test_hex_locale_key_resolves(lang: str, key: str) -> None:
    tm = TranslationManager()
    tm.load(lang)
    value = tm.get(key)
    # If the key were missing the manager returns the key itself.
    assert value != key, (
        f"missing {lang!r} translation for {key!r} "
        f"(falling back to the raw key)"
    )


def test_hex_biome_names_differ_between_languages() -> None:
    # Sanity: the three languages should actually give different
    # surface strings for at least one biome; catches the case where
    # somebody accidentally pastes the English text into ca.yaml /
    # es.yaml without translating.
    keys = [
        "hex.biome.greenlands",
        "hex.biome.forest",
        "hex.biome.mountain",
    ]
    values: dict[str, set[str]] = {"en": set(), "ca": set(), "es": set()}
    for lang in values:
        tm = TranslationManager()
        tm.load(lang)
        for k in keys:
            values[lang].add(tm.get(k))
    assert values["en"] != values["ca"]
    assert values["en"] != values["es"]

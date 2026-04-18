"""Integration tests for the bundled testland content pack and
the hex-related i18n keys in the three locale files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nhc.hexcrawl._generator import generate_continental_world
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
    assert pack.map.generator == "continental"
    # testland is a "bigger rectangular" sandbox.
    assert pack.map.width > pack.map.height, "pack is landscape"
    assert pack.map.width * pack.map.height >= 256
    assert pack.features.hub == 1
    # Ranges inflated for the bigger map; only sanity bounds here.
    assert pack.features.village.min >= 1
    assert pack.features.village.max >= pack.features.village.min
    assert pack.features.dungeon.min >= 3
    assert pack.features.dungeon.max >= pack.features.dungeon.min
    assert pack.features.wonder.min >= 1
    assert pack.features.wonder.max >= pack.features.wonder.min


def test_testland_locale_keys_file_populated() -> None:
    pack = load_pack(_pack_path())
    # testland does not ship its own locale_keys.yaml;
    # it reuses engine-level hex strings from the main locale
    # files. The loader returns an empty list when the sibling
    # file is absent.
    assert pack.locale_keys == []


# ---------------------------------------------------------------------------
# Generator via the real pack
# ---------------------------------------------------------------------------


def test_testland_generator_produces_valid_world() -> None:
    from nhc.hexcrawl.coords import expected_shape_cell_count
    pack = load_pack(_pack_path())
    world = generate_continental_world(seed=42, pack=pack)
    # Rectangular odd-q staggered shape (even cols carry
    # `height` hexes, odd cols `height - 1`).
    assert len(world.cells) == expected_shape_cell_count(
        pack.map.width, pack.map.height,
    )
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


@pytest.fixture(scope="module")
def translators() -> dict[str, TranslationManager]:
    """Load each locale once per module so the 45 parametrised
    ``test_hex_locale_key_resolves`` cases do not re-parse the
    ~2.4k-line YAMLs 45 times over."""
    out: dict[str, TranslationManager] = {}
    for lang in ("en", "ca", "es"):
        tm = TranslationManager()
        tm.load(lang)
        out[lang] = tm
    return out


@pytest.mark.parametrize("lang", ["en", "ca", "es"])
@pytest.mark.parametrize("key", _REQUIRED_KEYS)
def test_hex_locale_key_resolves(
    translators: dict[str, TranslationManager],
    lang: str,
    key: str,
) -> None:
    value = translators[lang].get(key)
    # If the key were missing the manager returns the key itself.
    assert value != key, (
        f"missing {lang!r} translation for {key!r} "
        f"(falling back to the raw key)"
    )


def test_hex_biome_names_differ_between_languages(
    translators: dict[str, TranslationManager],
) -> None:
    # Sanity: the three languages should actually give different
    # surface strings for at least one biome; catches the case where
    # somebody accidentally pastes the English text into ca.yaml /
    # es.yaml without translating.
    keys = [
        "hex.biome.greenlands",
        "hex.biome.forest",
        "hex.biome.mountain",
    ]
    values = {
        lang: {translators[lang].get(k) for k in keys}
        for lang in ("en", "ca", "es")
    }
    assert values["en"] != values["ca"]
    assert values["en"] != values["es"]

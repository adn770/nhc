"""Tests for the hexcrawl content-pack YAML loader."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from nhc.hexcrawl.model import Biome
from nhc.hexcrawl.pack import (
    DEFAULT_BIOME_COSTS,
    FeatureTarget,
    PackMeta,
    PackValidationError,
    load_pack,
)


_MINIMAL = textwrap.dedent(
    """
    id: testland
    version: 1
    attribution: "NHC test setting"
    map:
      generator: continental
      continental: {}
      width: 8
      height: 8
    """
)


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "pack.yaml"
    p.write_text(body)
    return p


# ---------------------------------------------------------------------------
# Happy-path loading
# ---------------------------------------------------------------------------


def test_pack_loads_minimal_yaml(tmp_path: Path) -> None:
    pack = load_pack(_write(tmp_path, _MINIMAL))
    assert isinstance(pack, PackMeta)
    assert pack.id == "testland"
    assert pack.version == 1
    assert pack.attribution == "NHC test setting"
    assert pack.map.generator == "continental"
    assert pack.map.width == 8
    assert pack.map.height == 8


def test_pack_loader_returns_packmeta_dataclass(tmp_path: Path) -> None:
    pack = load_pack(_write(tmp_path, _MINIMAL))
    # PackMeta is a dataclass; the field set is part of the contract.
    assert hasattr(pack, "id")
    assert hasattr(pack, "map")
    assert hasattr(pack, "features")
    assert hasattr(pack, "biome_costs")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_pack_rejects_missing_id(tmp_path: Path) -> None:
    body = textwrap.dedent(
        """
        version: 1
        map:
          generator: continental
          continental: {}
          width: 8
          height: 8
        """
    )
    with pytest.raises(PackValidationError, match="id"):
        load_pack(_write(tmp_path, body))


def test_pack_rejects_unknown_generator(tmp_path: Path) -> None:
    body = textwrap.dedent(
        """
        id: bad
        version: 1
        map:
          generator: noise
          width: 8
          height: 8
        """
    )
    with pytest.raises(PackValidationError, match="generator"):
        load_pack(_write(tmp_path, body))


def test_pack_validates_map_size_positive(tmp_path: Path) -> None:
    body = textwrap.dedent(
        """
        id: bad
        version: 1
        map:
          generator: continental
          continental: {}
          width: 0
          height: 8
        """
    )
    with pytest.raises(PackValidationError, match="width"):
        load_pack(_write(tmp_path, body))


def test_pack_validates_map_height_positive(tmp_path: Path) -> None:
    body = textwrap.dedent(
        """
        id: bad
        version: 1
        map:
          generator: continental
          continental: {}
          width: 8
          height: -3
        """
    )
    with pytest.raises(PackValidationError, match="height"):
        load_pack(_write(tmp_path, body))


def test_pack_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_pack(tmp_path / "nope.yaml")


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_pack_loads_default_biome_costs(tmp_path: Path) -> None:
    pack = load_pack(_write(tmp_path, _MINIMAL))
    assert pack.biome_costs == DEFAULT_BIOME_COSTS
    # Spot-check a couple of values from the design doc.
    assert pack.biome_costs[Biome.GREENLANDS] == 1
    assert pack.biome_costs[Biome.MOUNTAIN] == 4


def test_pack_loads_default_feature_targets(tmp_path: Path) -> None:
    pack = load_pack(_write(tmp_path, _MINIMAL))
    assert pack.features.hub == 1
    assert pack.features.village == FeatureTarget(1, 2)
    assert pack.features.dungeon == FeatureTarget(3, 5)
    assert pack.features.wonder == FeatureTarget(1, 3)


def test_pack_default_patterns_includes_caves_of_chaos(
    tmp_path: Path,
) -> None:
    """Without a patterns: key, the default enables caves_of_chaos."""
    pack = load_pack(_write(tmp_path, _MINIMAL))
    assert pack.features.patterns == ["caves_of_chaos"]


def test_pack_empty_patterns_disables_all(tmp_path: Path) -> None:
    body = _MINIMAL + textwrap.dedent(
        """
        features:
          patterns: []
        """
    )
    pack = load_pack(_write(tmp_path, body))
    assert pack.features.patterns == []


def test_pack_explicit_patterns_override_default(tmp_path: Path) -> None:
    body = _MINIMAL + textwrap.dedent(
        """
        features:
          patterns:
            - caves_of_chaos
        """
    )
    pack = load_pack(_write(tmp_path, body))
    assert pack.features.patterns == ["caves_of_chaos"]


def test_pack_rejects_unknown_pattern_name(tmp_path: Path) -> None:
    body = _MINIMAL + textwrap.dedent(
        """
        features:
          patterns:
            - not_a_real_pattern
        """
    )
    with pytest.raises(PackValidationError, match="pattern"):
        load_pack(_write(tmp_path, body))


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def test_pack_overrides_biome_costs(tmp_path: Path) -> None:
    body = _MINIMAL + textwrap.dedent(
        """
        biome_costs:
          greenlands: 2
          mountain: 6
        """
    )
    pack = load_pack(_write(tmp_path, body))
    assert pack.biome_costs[Biome.GREENLANDS] == 2
    assert pack.biome_costs[Biome.MOUNTAIN] == 6
    # Unmentioned biomes keep their defaults.
    assert pack.biome_costs[Biome.FOREST] == DEFAULT_BIOME_COSTS[Biome.FOREST]


def test_pack_overrides_feature_targets(tmp_path: Path) -> None:
    body = _MINIMAL + textwrap.dedent(
        """
        features:
          hub: 1
          village:
            min: 0
            max: 1
          dungeon:
            min: 5
            max: 7
          wonder:
            min: 0
            max: 0
        """
    )
    pack = load_pack(_write(tmp_path, body))
    assert pack.features.village == FeatureTarget(0, 1)
    assert pack.features.dungeon == FeatureTarget(5, 7)
    assert pack.features.wonder == FeatureTarget(0, 0)


def test_pack_rejects_unknown_biome_in_costs(tmp_path: Path) -> None:
    body = _MINIMAL + textwrap.dedent(
        """
        biome_costs:
          jungle: 2
        """
    )
    with pytest.raises(PackValidationError, match="biome"):
        load_pack(_write(tmp_path, body))


def test_pack_rejects_non_positive_biome_cost(tmp_path: Path) -> None:
    body = _MINIMAL + textwrap.dedent(
        """
        biome_costs:
          greenlands: 0
        """
    )
    with pytest.raises(PackValidationError, match="cost"):
        load_pack(_write(tmp_path, body))


def test_pack_rejects_inverted_feature_target(tmp_path: Path) -> None:
    body = _MINIMAL + textwrap.dedent(
        """
        features:
          dungeon:
            min: 5
            max: 2
        """
    )
    with pytest.raises(PackValidationError, match="dungeon"):
        load_pack(_write(tmp_path, body))


# ---------------------------------------------------------------------------
# Locale keys (optional sibling file)
# ---------------------------------------------------------------------------


def test_pack_resolves_locale_keys(tmp_path: Path) -> None:
    _write(tmp_path, _MINIMAL)
    (tmp_path / "locale_keys.yaml").write_text(
        textwrap.dedent(
            """
            keys:
              - content.testland.pack.name
              - content.testland.hex.hub.name
            """
        )
    )
    pack = load_pack(tmp_path / "pack.yaml")
    assert pack.locale_keys == [
        "content.testland.pack.name",
        "content.testland.hex.hub.name",
    ]


def test_pack_locale_keys_default_empty(tmp_path: Path) -> None:
    pack = load_pack(_write(tmp_path, _MINIMAL))
    assert pack.locale_keys == []


# ---------------------------------------------------------------------------
# Continental generator
# ---------------------------------------------------------------------------

_CONTINENTAL_V2 = textwrap.dedent(
    """
    id: testland
    version: 2
    attribution: "NHC test setting v2"
    map:
      generator: continental
      width: 25
      height: 16
      continental:
        continent_frequency: 0.06
        continent_octaves: 3
        island_falloff: 0.8
        sea_level: -0.25
        plate_count: 6
        warp_amplitude: 0.4
        warp_frequency: 0.15
        erosion_iterations: 4
        erosion_rate: 0.15
        deposit_rate: 0.3
        lake_chance: 0.3
    """
)


def test_pack_loads_continental(tmp_path: Path) -> None:
    pack = load_pack(_write(tmp_path, _CONTINENTAL_V2))
    assert pack.id == "testland"
    assert pack.map.generator == "continental"
    assert pack.map.continental is not None
    c = pack.map.continental
    assert c.continent_frequency == pytest.approx(0.06)
    assert c.continent_octaves == 3
    assert c.island_falloff == pytest.approx(0.8)
    assert c.sea_level == pytest.approx(-0.25)
    assert c.plate_count == 6
    assert c.warp_amplitude == pytest.approx(0.4)
    assert c.warp_frequency == pytest.approx(0.15)
    assert c.erosion_iterations == 4
    assert c.erosion_rate == pytest.approx(0.15)
    assert c.deposit_rate == pytest.approx(0.3)
    assert c.lake_chance == pytest.approx(0.3)


def test_continental_in_known_generators(tmp_path: Path) -> None:
    from nhc.hexcrawl.pack import KNOWN_GENERATORS
    assert "continental" in KNOWN_GENERATORS


def test_continental_defaults(tmp_path: Path) -> None:
    body = textwrap.dedent(
        """
        id: testland
        version: 2
        map:
          generator: continental
          width: 25
          height: 16
          continental: {}
        """
    )
    pack = load_pack(_write(tmp_path, body))
    c = pack.map.continental
    assert c is not None
    # All fields should have defaults
    assert c.continent_frequency > 0
    assert c.continent_octaves >= 1
    assert c.plate_count >= 2


def test_continental_missing_block_errors(tmp_path: Path) -> None:
    body = textwrap.dedent(
        """
        id: testland
        version: 2
        map:
          generator: continental
          width: 25
          height: 16
        """
    )
    with pytest.raises(PackValidationError, match="continental"):
        load_pack(_write(tmp_path, body))

"""Tests for the biome-features taxonomy (milestone 1).

Three new HexFeatureType values (COMMUNITY, TEMPLE, COTTAGE) and
two new FeatureTargets knobs (community, ruin) seed the biome-
features design. Tests confirm the enum entries exist, the
default pack knobs are inert, YAML parsing round-trips cleanly,
and the new feature -> site_kind mappings resolve.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nhc.hexcrawl._features import _site_kind_for, _template_for
from nhc.hexcrawl.model import HexFeatureType
from nhc.hexcrawl.pack import (
    FeatureTarget,
    FeatureTargets,
    load_pack,
)


# ---------------------------------------------------------------------------
# New enum values
# ---------------------------------------------------------------------------


class TestHexFeatureTypeNewValues:
    def test_hex_feature_type_has_community(self) -> None:
        assert HexFeatureType.COMMUNITY.value == "community"

    def test_hex_feature_type_has_temple(self) -> None:
        assert HexFeatureType.TEMPLE.value == "temple"

    def test_hex_feature_type_has_cottage(self) -> None:
        assert HexFeatureType.COTTAGE.value == "cottage"


# ---------------------------------------------------------------------------
# Pack schema defaults
# ---------------------------------------------------------------------------


class TestPackMetaDefaults:
    def test_pack_meta_community_range_default_zero(self) -> None:
        targets = FeatureTargets()
        assert isinstance(targets.community, FeatureTarget)
        assert targets.community.min == 0
        assert targets.community.max == 0

    def test_pack_meta_ruin_range_default_zero(self) -> None:
        targets = FeatureTargets()
        assert isinstance(targets.ruin, FeatureTarget)
        assert targets.ruin.min == 0
        assert targets.ruin.max == 0


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------


class TestPackYamlRoundTrip:
    def test_pack_meta_parses_community_and_ruin_from_yaml(
        self, tmp_path: Path,
    ) -> None:
        yaml_text = """
id: tiny
version: 1
attribution: "test fixture"
map:
  generator: continental
  width: 8
  height: 8
  continental:
    continent_frequency: 0.05
features:
  hub: 1
  village:
    min: 1
    max: 2
  community:
    min: 2
    max: 5
  ruin:
    min: 2
    max: 4
  dungeon:
    min: 3
    max: 5
  wonder:
    min: 1
    max: 2
"""
        pack_yaml = tmp_path / "pack.yaml"
        pack_yaml.write_text(yaml_text)
        meta = load_pack(pack_yaml)
        assert meta.features.community == FeatureTarget(2, 5)
        assert meta.features.ruin == FeatureTarget(2, 4)


# ---------------------------------------------------------------------------
# Feature -> site_kind
# ---------------------------------------------------------------------------


class TestSiteKindForNewFeatures:
    def test_community_maps_to_town(self) -> None:
        assert _site_kind_for(HexFeatureType.COMMUNITY) == "town"

    def test_temple_maps_to_temple(self) -> None:
        assert _site_kind_for(HexFeatureType.TEMPLE) == "temple"

    def test_cottage_maps_to_cottage(self) -> None:
        assert _site_kind_for(HexFeatureType.COTTAGE) == "cottage"

    def test_ruin_maps_to_ruin(self) -> None:
        assert _site_kind_for(HexFeatureType.RUIN) == "ruin"


# ---------------------------------------------------------------------------
# Feature -> template
# ---------------------------------------------------------------------------


class TestTemplateForNewFeatures:
    def test_community_template_is_procedural_settlement(self) -> None:
        assert _template_for(HexFeatureType.COMMUNITY) == (
            "procedural:settlement"
        )

    def test_temple_template_is_site_temple(self) -> None:
        assert _template_for(HexFeatureType.TEMPLE) == "site:temple"

    def test_cottage_template_is_site_cottage(self) -> None:
        assert _template_for(HexFeatureType.COTTAGE) == "site:cottage"

    def test_ruin_template_unchanged(self) -> None:
        assert _template_for(HexFeatureType.RUIN) == "procedural:ruin"

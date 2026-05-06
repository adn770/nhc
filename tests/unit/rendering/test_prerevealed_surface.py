"""Site surfaces ship with ``metadata.prerevealed = True`` so the web
client suppresses fog of war and the SVG renderer skips hatching. A
pre-M1 save that landed on a site surface is silently upgraded on load
so existing sessions don't stay fogged after the patch.
"""

from __future__ import annotations

import json
import random

import pytest

from nhc.core.save import _deserialize_level, _serialize_level
from nhc.dungeon.model import (
    Level,
    LevelMetadata,
    Terrain,
)
from nhc.sites._site import assemble_site
from nhc.rendering.svg import render_floor_svg


SITE_KINDS = (
    "town", "keep", "ruin", "cottage", "temple",
    "mansion", "tower", "mage_residence",
)


class TestLevelMetadataField:
    def test_default_prerevealed_false(self) -> None:
        meta = LevelMetadata()
        assert meta.prerevealed is False

    def test_prerevealed_can_be_set(self) -> None:
        meta = LevelMetadata(prerevealed=True)
        assert meta.prerevealed is True


class TestSiteSurfacePrerevealedFlag:
    @pytest.mark.parametrize("kind", SITE_KINDS)
    def test_site_surface_is_prerevealed(self, kind: str) -> None:
        site = assemble_site(kind, f"{kind}_pr", random.Random(7))
        assert site.surface.metadata is not None
        assert site.surface.metadata.prerevealed is True, (
            f"{kind} surface must carry prerevealed=True"
        )

    @pytest.mark.parametrize("kind", SITE_KINDS)
    def test_site_surface_theme_is_not_dungeon(self, kind: str) -> None:
        """Surface metadata must carry a site-specific theme so the
        v5 emit pipeline routes through the surface code paths
        (palette + ``floor_kind == 'surface'``) instead of falling
        back to the dungeon defaults."""
        site = assemble_site(kind, f"{kind}_th", random.Random(7))
        assert site.surface.metadata is not None
        assert site.surface.metadata.theme != "dungeon", (
            f"{kind} surface theme must not fall back to 'dungeon'"
        )

    def test_tower_interior_is_not_prerevealed(self) -> None:
        """Sanity: a building-interior level (tower ground floor)
        never gets the prereveal flag -- those are dungeons."""
        site = assemble_site("tower", "tw", random.Random(3))
        ground = site.buildings[0].ground
        assert ground.metadata is not None
        assert ground.metadata.prerevealed is False


class TestHatchingSuppressedOnPrerevealed:
    """``render_floor_svg`` skips the hatching passes when the level is
    prerevealed. The check used to read ``theme == 'settlement'`` — a
    string nothing ever set — so towns shipped with hatching."""

    def test_prerevealed_level_has_no_hatch_clip(self) -> None:
        from nhc.rendering._svg_helpers import HATCH_UNDERLAY

        site = assemble_site("town", "tnh", random.Random(11))
        svg = render_floor_svg(site.surface, seed=11)
        # Phase 1.21a dropped the `<g clip-path="url(#hatch-clip)">`
        # wrapper; the prerevealed-suppression check now uses the
        # hatch underlay colour as the "is hatching present?" proxy.
        # A prerevealed level skips the hatching emit entirely so the
        # underlay must not appear.
        assert HATCH_UNDERLAY not in svg, (
            "prerevealed level must not emit any hatching elements"
        )

    def test_regular_dungeon_still_emits_hatching(self) -> None:
        """Guard: non-prerevealed dungeon levels continue to emit
        hatching elements. If they don't, the new check is too broad."""
        from nhc.dungeon.pipeline import generate_level as gen_level
        from nhc.dungeon.generator import GenerationParams
        from nhc.rendering._svg_helpers import HATCH_UNDERLAY

        params = GenerationParams(
            width=30, height=20, depth=1, seed=42,
            shape_variety=0.0, template="procedural:dungeon",
        )
        level = gen_level(params)
        svg = render_floor_svg(level, seed=42)
        assert HATCH_UNDERLAY in svg, (
            "non-prerevealed dungeon lost its hatching"
        )


class TestSaveRoundTripAndAutoUpgrade:
    def test_prerevealed_true_survives_round_trip(self) -> None:
        level = Level.create_empty("test", "test", 0, 4, 4)
        level.metadata.theme = "town"
        level.metadata.prerevealed = True
        data = _serialize_level(level)
        # Fresh-JSON simulation for safety.
        round_tripped = _deserialize_level(json.loads(json.dumps(data)))
        assert round_tripped.metadata.prerevealed is True

    def test_pre_m1_town_save_auto_upgrades(self) -> None:
        """A save blob from before M1 lacks ``prerevealed`` entirely.
        When deserialising a site-surface-shaped level (theme is a
        site-surface kind and the rooms list is empty) the loader
        silently promotes it to ``prerevealed=True`` so the session
        doesn't stay fogged after the patch lands."""
        level = Level.create_empty("legacy", "legacy", 0, 4, 4)
        level.metadata.theme = "town"
        data = _serialize_level(level)
        data["metadata"].pop("prerevealed", None)
        assert data.get("rooms") in (None, [])
        upgraded = _deserialize_level(data)
        assert upgraded.metadata.prerevealed is True

    def test_pre_m1_dungeon_save_stays_fogged(self) -> None:
        """Guard: a legacy dungeon save without prerevealed must stay
        False. The shim only fires for site-surface themes."""
        level = Level.create_empty("dd", "dd", 1, 4, 4)
        level.metadata.theme = "dungeon"
        data = _serialize_level(level)
        data["metadata"].pop("prerevealed", None)
        loaded = _deserialize_level(data)
        assert loaded.metadata.prerevealed is False

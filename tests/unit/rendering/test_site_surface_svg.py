"""Wrapper that composes the game's site-surface SVG.

Site surfaces (town, keep, ruin, cottage, temple courtyards) used
to ship as bare floor SVG -- no rooftops, no palisade. M5 wires
the roof generator (every site kind) and the enclosure renderer
(town + keep only per Q5) onto the surface SVG so the web client
sees the same composed image the sample generator has been
producing for months.
"""

from __future__ import annotations

import random

from nhc.dungeon.site import assemble_site
from nhc.rendering.site_svg import render_site_surface_svg


_ROOF_CLIP_MARKER = 'id="roof_fp_'
# Palisade is drawn as a ring of brown circles; fortification is
# a ring of black rectangles with a distinct stone border.
_PALISADE_MARKER = 'fill="#8A5A2A"'
_FORTIFICATION_MARKER = 'stroke="#1A1A1A"'


class TestRenderSiteSurfaceSvg:
    def test_town_has_roofs_and_palisade(self) -> None:
        site = assemble_site("town", "t_svg", random.Random(3))
        svg = render_site_surface_svg(site, seed=3)
        assert _ROOF_CLIP_MARKER in svg, (
            "town surface must include clipped roof footprints"
        )
        assert _PALISADE_MARKER in svg, (
            "town surface must include palisade stakes"
        )

    def test_keep_has_roofs_and_fortification(self) -> None:
        site = assemble_site("keep", "k_svg", random.Random(3))
        svg = render_site_surface_svg(site, seed=3)
        assert _ROOF_CLIP_MARKER in svg
        assert _FORTIFICATION_MARKER in svg, (
            "keep surface must include fortification blocks"
        )

    def test_cottage_has_roofs_only(self) -> None:
        site = assemble_site("cottage", "c_svg", random.Random(3))
        svg = render_site_surface_svg(site, seed=3)
        assert _ROOF_CLIP_MARKER in svg
        # Cottage has no palisade; no fortification either.
        assert _PALISADE_MARKER not in svg
        assert _FORTIFICATION_MARKER not in svg

    def test_ruin_has_roofs_but_no_enclosure(self) -> None:
        """Q5: enclosures only for town / keep. Ruin carries a
        broken fortification in its data model but M5 doesn't
        render it -- that geometry is a follow-up milestone."""
        site = assemble_site("ruin", "r_svg", random.Random(3))
        svg = render_site_surface_svg(site, seed=3)
        assert _ROOF_CLIP_MARKER in svg
        assert _PALISADE_MARKER not in svg
        assert _FORTIFICATION_MARKER not in svg

    def test_temple_has_roofs_only(self) -> None:
        site = assemble_site("temple", "te_svg", random.Random(3))
        svg = render_site_surface_svg(site, seed=3)
        assert _ROOF_CLIP_MARKER in svg
        assert _PALISADE_MARKER not in svg
        assert _FORTIFICATION_MARKER not in svg

    def test_output_closes_svg_tag(self) -> None:
        site = assemble_site("town", "t_close", random.Random(1))
        svg = render_site_surface_svg(site, seed=1)
        assert svg.rstrip().endswith("</svg>")

    def test_overlay_appears_before_closing_svg(self) -> None:
        """Roofs / enclosure must sit inside the <svg> element,
        not after it -- otherwise the browser ignores them."""
        site = assemble_site("town", "t_inside", random.Random(1))
        svg = render_site_surface_svg(site, seed=1)
        end = svg.rindex("</svg>")
        assert _ROOF_CLIP_MARKER in svg[:end]


class TestGoldenSnapshot:
    """Byte-for-byte regression trip wire. When this test fails,
    regenerate the golden via
    ``tests/samples/golden/regenerate_town_surface.py`` (or by
    hand) and inspect the diff in the PR before blessing the new
    bytes. Seed 7 was picked because it yields a town with a
    palisade, seven buildings, and at least one L-shape, so the
    golden covers gable, pyramid, and polygon-clipping paths."""

    GOLDEN_SEED = 7

    def test_town_surface_matches_golden(self) -> None:
        from pathlib import Path
        site = assemble_site(
            "town", f"town_seed{self.GOLDEN_SEED}",
            random.Random(self.GOLDEN_SEED),
        )
        got = render_site_surface_svg(site, seed=self.GOLDEN_SEED)
        golden = Path(
            "tests/samples/golden/"
            f"town_surface_seed{self.GOLDEN_SEED}.svg"
        ).read_text()
        assert got == golden, (
            "Site-surface SVG drift. Inspect the diff; if the "
            "change is intentional, regenerate the golden:\n\n"
            "    .venv/bin/python -c 'import random; "
            "from nhc.dungeon.site import assemble_site; "
            "from nhc.rendering.site_svg import render_site_surface_svg; "
            f"seed={self.GOLDEN_SEED}; "
            "site=assemble_site(\"town\", f\"town_seed{seed}\", "
            "random.Random(seed)); "
            "open(f\"tests/samples/golden/"
            "town_surface_seed{seed}.svg\", \"w\")"
            ".write(render_site_surface_svg(site, seed=seed))'"
        )


class TestRenderLevelSvgDispatch:
    """When the Level is a Site's surface, render_level_svg must
    route through render_site_surface_svg so rooftops land on the
    web client's floor SVG."""

    def test_town_surface_goes_through_wrapper(self) -> None:
        from nhc.rendering.level_svg import render_level_svg
        site = assemble_site("town", "t_disp", random.Random(2))
        svg = render_level_svg(site.surface, site, seed=2)
        assert _ROOF_CLIP_MARKER in svg
        assert _PALISADE_MARKER in svg

    def test_dungeon_level_bypasses_wrapper(self) -> None:
        """Plain dungeon floors (no site) still go through
        render_floor_svg -- no roofs, no enclosure markers."""
        from nhc.dungeon.generator import GenerationParams
        from nhc.dungeon.pipeline import generate_level
        from nhc.rendering.level_svg import render_level_svg
        params = GenerationParams(
            width=30, height=20, depth=1, seed=11,
            shape_variety=0.0, template="procedural:dungeon",
        )
        level = generate_level(params)
        svg = render_level_svg(level, None, seed=11)
        assert _ROOF_CLIP_MARKER not in svg

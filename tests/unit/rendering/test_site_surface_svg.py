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
from pathlib import Path

import pytest

from nhc.sites._site import assemble_site
from nhc.rendering.site_svg import render_site_surface_svg


# Hard ceiling on the AssertionError message emitted on golden
# drift. Keeps pytest's assertion rewriter from feeding multi-MB
# operands to difflib.SequenceMatcher, whose _fancy_replace /
# find_longest_match goes O(n²)+ on large near-matching strings
# and wedges CI for minutes per failing iteration.
_GOLDEN_DRIFT_MSG_CEILING = 4096


def _assert_svg_matches_golden(got: str, golden_path: Path) -> None:
    """Byte-compare ``got`` against the golden SVG at ``golden_path``.

    Raises a bare ``AssertionError`` (not a rewritten ``assert`` with
    the operands attached) so pytest's diff pretty-printer never sees
    the full multi-MB strings.
    """
    golden = golden_path.read_text()
    if got == golden:
        return
    for i, (a, b) in enumerate(zip(got, golden)):
        if a != b:
            offset = i
            break
    else:
        offset = min(len(got), len(golden))
    ctx = 80
    start = max(0, offset - ctx // 2)
    got_snip = got[start:start + ctx]
    golden_snip = golden[start:start + ctx]
    raise AssertionError(
        f"SVG drift at offset {offset} "
        f"(got {len(got)}B, golden {len(golden)}B).\n"
        f"got    : {got_snip!r}\n"
        f"golden : {golden_snip!r}\n"
        f"Regenerate: .venv/bin/python -c 'import random; "
        f"from nhc.sites._site import assemble_site; "
        f"from nhc.rendering.site_svg import render_site_surface_svg; "
        f"seed=7; "
        f'site=assemble_site("town", f"town_seed{{seed}}", '
        f"random.Random(seed)); "
        f'open(f"{golden_path}", "w")'
        f".write(render_site_surface_svg(site, seed=seed))'"
    )


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
    """Byte-for-byte regression trip wire. Seed 7 was picked
    because it yields a town with a palisade, seven buildings,
    and at least one L-shape, so the golden covers gable, pyramid,
    and polygon-clipping paths. On drift the helper below fails
    fast with a short, bounded message — see _assert_svg_matches_golden
    for why we avoid a bare ``assert got == golden``."""

    GOLDEN_SEED = 7

    def test_town_surface_matches_golden(self) -> None:
        site = assemble_site(
            "town", f"town_seed{self.GOLDEN_SEED}",
            random.Random(self.GOLDEN_SEED),
        )
        got = render_site_surface_svg(site, seed=self.GOLDEN_SEED)
        golden_path = Path(
            "tests/samples/golden/"
            f"town_surface_seed{self.GOLDEN_SEED}.svg"
        )
        _assert_svg_matches_golden(got, golden_path)


class TestAssertSvgMatchesGolden:
    """Guards the helper that compares generated SVGs to golden
    files. The helper must: (a) pass silently on exact match;
    (b) on mismatch, raise an AssertionError whose message stays
    well under the difflib-pathology threshold even for multi-MB
    operands; (c) report a useful byte offset and snippet."""

    def test_passes_on_exact_match(self, tmp_path: Path) -> None:
        golden = tmp_path / "g.svg"
        golden.write_text("<svg>hello</svg>")
        _assert_svg_matches_golden("<svg>hello</svg>", golden)

    def test_raises_on_mismatch(self, tmp_path: Path) -> None:
        golden = tmp_path / "g.svg"
        golden.write_text("<svg>hello</svg>")
        with pytest.raises(AssertionError, match="SVG drift"):
            _assert_svg_matches_golden("<svg>world</svg>", golden)

    def test_message_is_bounded_for_huge_operands(
        self, tmp_path: Path
    ) -> None:
        """Core protection: a 3 MB near-matching mismatch must
        still emit a small message. Before this helper, pytest's
        assertion rewriter fed such operands to difflib and hung
        the suite for >5 minutes per failing iteration."""
        golden_text = "<svg>" + ("a" * 3_000_000) + "</svg>"
        got = "<svg>" + ("a" * 1_500_000) + "b" + (
            "a" * 1_499_999
        ) + "</svg>"
        golden = tmp_path / "g.svg"
        golden.write_text(golden_text)
        with pytest.raises(AssertionError) as excinfo:
            _assert_svg_matches_golden(got, golden)
        assert len(str(excinfo.value)) <= _GOLDEN_DRIFT_MSG_CEILING

    def test_reports_divergence_offset(self, tmp_path: Path) -> None:
        golden = tmp_path / "g.svg"
        golden.write_text("abcdefghij")
        with pytest.raises(AssertionError) as excinfo:
            _assert_svg_matches_golden("abcdeXghij", golden)
        assert "offset 5" in str(excinfo.value)


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

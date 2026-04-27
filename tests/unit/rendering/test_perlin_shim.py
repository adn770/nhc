"""Perlin shim contract tests.

`nhc.rendering._perlin` replaces the abandoned `noise` PyPI package
(last released 2017, no cp314 wheel). It provides a single public
function, `pnoise2(x, y, base=0)`, that the rendering subsystem
calls in place of `noise.pnoise2`.

These tests pin the contract that future Rust ports (IR migration
Phase 4) and any drop-in replacement must honour. They do NOT
attempt byte-equal parity with the legacy `noise` package — that
parity intentionally drops, and the SVG fixtures under
`tests/samples/golden/` regenerate against this shim.
"""

from __future__ import annotations

import math

import pytest

from nhc.rendering._perlin import pnoise2


class TestDeterminism:
    """Same input must produce the same output, every time."""

    def test_repeated_call_returns_identical_value(self) -> None:
        a = pnoise2(1.5, 2.7)
        b = pnoise2(1.5, 2.7)
        assert a == b

    def test_repeated_call_with_base_returns_identical_value(self) -> None:
        a = pnoise2(0.3, -1.1, base=5)
        b = pnoise2(0.3, -1.1, base=5)
        assert a == b

    def test_negative_inputs_are_deterministic(self) -> None:
        a = pnoise2(-3.7, -2.4)
        b = pnoise2(-3.7, -2.4)
        assert a == b


class TestRange:
    """Output magnitude must stay bounded — required by the
    rendering callers, which scale the value by a small constant
    (e.g. ``0.1 * cell``) and trust it not to blow out."""

    def test_output_is_within_unit_interval(self) -> None:
        # Sweep a 32x32 grid with sub-cell offsets, assert |output| <= 1.
        for xi in range(-4, 4):
            for yi in range(-4, 4):
                for fx in (0.0, 0.25, 0.5, 0.75):
                    for fy in (0.0, 0.25, 0.5, 0.75):
                        v = pnoise2(xi + fx, yi + fy)
                        assert -1.0 <= v <= 1.0, (
                            f"out of range at ({xi+fx}, {yi+fy}): {v}"
                        )

    def test_output_with_base_is_within_unit_interval(self) -> None:
        for base in range(8):
            for xi in range(8):
                for yi in range(8):
                    v = pnoise2(xi + 0.3, yi + 0.7, base=base)
                    assert -1.0 <= v <= 1.0


class TestLatticeProperty:
    """Classic Perlin noise has value 0 at every integer lattice
    point (the offset-from-corner is the zero vector at corners,
    and the dot product with any gradient is 0). This is a strong
    correctness property — implementations that fail it have an
    off-by-one bug in the coordinate fractional split."""

    @pytest.mark.parametrize(
        "x,y",
        [
            (0.0, 0.0),
            (1.0, 0.0),
            (0.0, 1.0),
            (-1.0, 0.0),
            (0.0, -1.0),
            (3.0, 5.0),
            (-7.0, 4.0),
            (10.0, 10.0),
        ],
    )
    def test_zero_at_integer_lattice(self, x: float, y: float) -> None:
        assert math.isclose(pnoise2(x, y), 0.0, abs_tol=1e-9)


class TestBaseDecorrelates:
    """Different `base` values must produce decorrelated patterns
    for the same (x, y). The rendering code samples
    ``pnoise2(x, y, base=1)`` and ``pnoise2(x, y, base=2)`` to get
    two independent random offsets — they MUST NOT collapse to
    the same value."""

    def test_distinct_bases_diverge_on_average(self) -> None:
        diffs = []
        for xi in range(8):
            for yi in range(8):
                a = pnoise2(xi + 0.3, yi + 0.7, base=1)
                b = pnoise2(xi + 0.3, yi + 0.7, base=2)
                diffs.append(abs(a - b))
        avg_diff = sum(diffs) / len(diffs)
        # Mean-absolute-deviation across a 64-sample grid should be
        # well above zero. Empirically ~0.2-0.4 for any reasonable
        # Perlin impl; threshold deliberately loose.
        assert avg_diff > 0.05, (
            f"base param does not decorrelate (mean abs diff "
            f"{avg_diff:.4f})"
        )

    def test_distinct_bases_at_one_point_differ(self) -> None:
        # At least one (x, y) sample must produce different values for
        # different bases. If this fails, base is ignored entirely.
        a = pnoise2(0.3, 0.7, base=1)
        b = pnoise2(0.3, 0.7, base=2)
        assert a != b


class TestContinuity:
    """Small perturbations to the input must produce small
    perturbations to the output. Without this property, the wobble
    paths and hatch jitter would become visually chaotic."""

    def test_small_x_perturbation_yields_small_output_delta(self) -> None:
        a = pnoise2(1.0, 2.0)
        b = pnoise2(1.001, 2.0)
        assert abs(a - b) < 0.01

    def test_small_y_perturbation_yields_small_output_delta(self) -> None:
        a = pnoise2(1.0, 2.0)
        b = pnoise2(1.0, 2.001)
        assert abs(a - b) < 0.01


class TestApiCompat:
    """Drop-in compatibility with the call sites we replace."""

    def test_keyword_base_argument(self) -> None:
        # Three usage styles in the codebase:
        # - pnoise2(x, y)
        # - pnoise2(x, y, base=N)
        # All must accept current call signatures without raising.
        pnoise2(0.5, 0.5)
        pnoise2(0.5, 0.5, base=0)
        pnoise2(0.5, 0.5, base=11)

    def test_returns_float(self) -> None:
        assert isinstance(pnoise2(0.5, 0.5), float)
        assert isinstance(pnoise2(0.5, 0.5, base=3), float)

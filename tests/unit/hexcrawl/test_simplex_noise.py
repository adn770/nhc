"""2D simplex noise (M-G.3).

Pins the contract ``nhc.hexcrawl.noise.SimplexNoise`` must
satisfy so the noise-based generator (M-G.4) can rely on
deterministic, bounded, continuous samples.
"""

from __future__ import annotations

import math
import random

import pytest

from nhc.hexcrawl.noise import SimplexNoise


# ---------------------------------------------------------------------------
# Range + determinism
# ---------------------------------------------------------------------------


def test_sample_output_in_unit_range() -> None:
    n = SimplexNoise(seed=1)
    rng = random.Random(0)
    for _ in range(200):
        x = rng.uniform(-50, 50)
        y = rng.uniform(-50, 50)
        v = n.sample(x, y)
        assert -1.0 <= v <= 1.0, (
            f"sample({x}, {y}) = {v} outside [-1, 1]"
        )


def test_sample_seed_reproducibility() -> None:
    a = SimplexNoise(seed=42)
    b = SimplexNoise(seed=42)
    rng = random.Random(0)
    for _ in range(50):
        x = rng.uniform(-10, 10)
        y = rng.uniform(-10, 10)
        assert a.sample(x, y) == b.sample(x, y)


def test_different_seeds_differ() -> None:
    a = SimplexNoise(seed=1)
    b = SimplexNoise(seed=2)
    rng = random.Random(0)
    diffs = 0
    for _ in range(50):
        x = rng.uniform(-10, 10)
        y = rng.uniform(-10, 10)
        if abs(a.sample(x, y) - b.sample(x, y)) > 1e-9:
            diffs += 1
    assert diffs > 40, (
        f"expected different seeds to produce different samples, "
        f"got only {diffs}/50 differing"
    )


# ---------------------------------------------------------------------------
# Fractal FBM
# ---------------------------------------------------------------------------


def test_fractal_output_in_unit_range() -> None:
    n = SimplexNoise(seed=1)
    rng = random.Random(0)
    for _ in range(200):
        x = rng.uniform(-50, 50)
        y = rng.uniform(-50, 50)
        v = n.fractal(x, y, octaves=4, persistence=0.5)
        assert -1.0 <= v <= 1.0, (
            f"fractal({x}, {y}) = {v} outside [-1, 1]"
        )


def test_fractal_seed_reproducibility() -> None:
    a = SimplexNoise(seed=7)
    b = SimplexNoise(seed=7)
    rng = random.Random(0)
    for _ in range(30):
        x = rng.uniform(-20, 20)
        y = rng.uniform(-20, 20)
        assert (
            a.fractal(x, y, octaves=3)
            == b.fractal(x, y, octaves=3)
        )


def test_fractal_octave_count_zero_rejected() -> None:
    n = SimplexNoise(seed=1)
    with pytest.raises(ValueError):
        n.fractal(0.0, 0.0, octaves=0)


# ---------------------------------------------------------------------------
# Continuity
# ---------------------------------------------------------------------------


def test_noise_is_continuous() -> None:
    """Noise samples at nearby points should be close -- this is
    what distinguishes simplex from white noise."""
    n = SimplexNoise(seed=1)
    rng = random.Random(0)
    for _ in range(50):
        x = rng.uniform(-20, 20)
        y = rng.uniform(-20, 20)
        dx = 0.01
        dy = 0.01
        v1 = n.sample(x, y)
        v2 = n.sample(x + dx, y + dy)
        # Simplex gradients are bounded so a tiny step shouldn't
        # jump by more than ~0.1 in value. Loose threshold to
        # stay robust across implementations.
        assert abs(v1 - v2) < 0.15, (
            f"step of ({dx}, {dy}) produced jump of "
            f"{abs(v1 - v2)} -- not continuous"
        )


def test_zero_origin_is_not_always_zero() -> None:
    """The canonical simplex implementation returns 0 at the
    origin by design; our seeded variant must offset the
    lookup so different seeds produce different origin values."""
    seen = {
        SimplexNoise(seed=s).sample(0.0, 0.0)
        for s in range(10)
    }
    assert len(seen) > 1, (
        f"expected seed-varied samples at origin, got {seen}"
    )


# ---------------------------------------------------------------------------
# Spectral proxy: higher octaves add detail
# ---------------------------------------------------------------------------


def test_higher_octaves_materially_change_output() -> None:
    """Adding more octaves actually changes the fractal output.

    A 1-octave FBM is just raw simplex; a 5-octave FBM sums in
    higher-frequency components normalised by amplitude. The
    two should differ non-trivially across a sample set.
    Pure "same output regardless of octaves" would mean the
    amplitude normalisation erases all added detail, which is a
    real failure mode worth guarding against.
    """
    n = SimplexNoise(seed=1)
    rng = random.Random(0)
    total_delta = 0.0
    for _ in range(64):
        x = rng.uniform(-20, 20)
        y = rng.uniform(-20, 20)
        v1 = n.fractal(x, y, octaves=1)
        v5 = n.fractal(x, y, octaves=5)
        total_delta += abs(v5 - v1)
    mean_delta = total_delta / 64
    assert mean_delta > 0.05, (
        f"octave=1 vs octave=5 outputs are nearly identical "
        f"(mean|Δ|={mean_delta:.4f}); higher octaves must "
        f"materially affect the fractal output"
    )

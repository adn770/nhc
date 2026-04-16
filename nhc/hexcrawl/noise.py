"""Minimal 2D simplex noise for the hex world generator.

No external dependencies. Based on Stefan Gustavson's public-
domain 2002 simplex noise reference; a clean-room Python port
that reorders the permutation table per seed so two
:class:`SimplexNoise` instances with different seeds produce
materially different output.

The generator is not a cryptographic RNG -- it's a deterministic
gradient field, smooth and bounded in ``[-1, 1]`` (normalised
from simplex's native ~``[-1, 1]`` range; fractal sums are
re-normalised to stay in the same unit range).

Usage:

    noise = SimplexNoise(seed=42)
    n = noise.sample(x, y)                    # single octave
    m = noise.fractal(x, y, octaves=4)        # FBM sum

Two-field use for the generator:

    elevation = noise.fractal(x * 0.08, y * 0.08, octaves=4)
    moisture  = moisture_noise.fractal(x * 0.12, y * 0.12)

The caller supplies the coord scaling; there's no implicit
frequency inside ``sample`` / ``fractal``.
"""

from __future__ import annotations

import math
import random


# Simplex noise skew/unskew factors for 2D.
_F2 = 0.5 * (math.sqrt(3.0) - 1.0)
_G2 = (3.0 - math.sqrt(3.0)) / 6.0


# 12 gradient vectors on the unit circle (3D reference, 2D uses
# the x/y components). The canonical Gustavson set; scaled so
# dot products stay in the expected range.
_GRAD3: tuple[tuple[float, float], ...] = (
    (1, 1), (-1, 1), (1, -1), (-1, -1),
    (1, 0), (-1, 0), (1, 0), (-1, 0),
    (0, 1), (0, -1), (0, 1), (0, -1),
)


class SimplexNoise:
    """Seedable 2D simplex noise."""

    def __init__(self, seed: int) -> None:
        # Build a seed-permuted index table so different seeds
        # produce different output. The canonical simplex uses a
        # fixed permutation; we shuffle ours per-seed and then
        # double it (standard trick) so index wrap math stays
        # branch-free.
        self._seed = int(seed)
        rng = random.Random(self._seed)
        perm = list(range(256))
        rng.shuffle(perm)
        self._perm: tuple[int, ...] = tuple(perm + perm)
        # Per-seed origin offset: canonical simplex returns 0 at
        # the origin by construction, which would make every
        # SimplexNoise(seed=X).sample(0, 0) identical. Offsetting
        # the lookup per seed is the standard fix.
        self._ox: float = rng.uniform(-1000.0, 1000.0)
        self._oy: float = rng.uniform(-1000.0, 1000.0)

    # ─────────────────────────────────────────────────────────

    def sample(self, x: float, y: float) -> float:
        """Single-octave simplex noise at ``(x, y)``.

        Returns a value in ``[-1, 1]`` (practically; simplex is
        bounded by design but the raw scalar is renormalised
        into ``[-1, 1]`` by the Gustavson constant).
        """
        # Apply the per-seed origin offset so seed 0 at (0, 0)
        # doesn't collide with seed 1 at (0, 0) at the canonical
        # zero-value origin.
        x += self._ox
        y += self._oy
        # Skew input to determine which simplex cell we're in.
        s = (x + y) * _F2
        i = math.floor(x + s)
        j = math.floor(y + s)
        t = (i + j) * _G2
        x0 = x - (i - t)
        y0 = y - (j - t)

        # For 2D the simplex is a triangle; determine which of the
        # two possible orientations.
        if x0 > y0:
            i1, j1 = 1, 0
        else:
            i1, j1 = 0, 1

        x1 = x0 - i1 + _G2
        y1 = y0 - j1 + _G2
        x2 = x0 - 1.0 + 2.0 * _G2
        y2 = y0 - 1.0 + 2.0 * _G2

        perm = self._perm
        ii = int(i) & 255
        jj = int(j) & 255
        gi0 = perm[ii + perm[jj]] % 12
        gi1 = perm[ii + i1 + perm[jj + j1]] % 12
        gi2 = perm[ii + 1 + perm[jj + 1]] % 12

        def _contrib(x_: float, y_: float, gi: int) -> float:
            t_ = 0.5 - x_ * x_ - y_ * y_
            if t_ < 0.0:
                return 0.0
            t_ *= t_
            gx, gy = _GRAD3[gi]
            return t_ * t_ * (gx * x_ + gy * y_)

        n0 = _contrib(x0, y0, gi0)
        n1 = _contrib(x1, y1, gi1)
        n2 = _contrib(x2, y2, gi2)
        # Magic normalisation constant from Gustavson's reference;
        # brings simplex's raw output into roughly [-1, 1].
        raw = 70.0 * (n0 + n1 + n2)
        # Clamp residuals from the rational constant; the raw
        # scalar is bounded in theory but floating-point round-
        # off can nudge it a few ULPs beyond the bound.
        return max(-1.0, min(1.0, raw))

    # ─────────────────────────────────────────────────────────

    def fractal(
        self,
        x: float,
        y: float,
        *,
        octaves: int = 4,
        persistence: float = 0.5,
        lacunarity: float = 2.0,
    ) -> float:
        """Fractional Brownian Motion (FBM) sum of octaves.

        Each octave doubles the frequency (``lacunarity``) and
        halves the amplitude (``persistence``). The total is
        divided by the sum of amplitudes so the result stays in
        ``[-1, 1]``.
        """
        if octaves < 1:
            raise ValueError(f"octaves must be >= 1, got {octaves}")
        total = 0.0
        amplitude = 1.0
        frequency = 1.0
        max_amp = 0.0
        for _ in range(octaves):
            total += amplitude * self.sample(
                x * frequency, y * frequency,
            )
            max_amp += amplitude
            amplitude *= persistence
            frequency *= lacunarity
        return total / max_amp if max_amp > 0 else 0.0

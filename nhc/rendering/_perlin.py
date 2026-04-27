"""Pure-Python Perlin noise shim.

Replacement for the abandoned ``noise`` PyPI package (last released
in 2017, no Python 3.14 wheel). Exposes a single function,
``pnoise2(x, y, base=0)``, with the same call shape as
``noise.pnoise2``. Output is NOT byte-equal to the legacy package —
SVG fixtures regenerate against this implementation as the new
parity reference.

Perlin's improved-noise algorithm: cubic-fade interpolation of dot
products between offset-from-corner vectors and per-corner pseudo-
random gradients selected from an 8-direction set. Output at every
integer lattice point is exactly 0.

The IR migration's Phase 4 ports this to Rust as the canonical
procedural source; this module is the Python-side stepping stone
until then.
"""

from __future__ import annotations

import math


# Ken Perlin's reference permutation table, from the 2002 improved-
# noise paper. The duplicated half eliminates bounds checks on the
# second-level lookup.
_PERM_BASE = (
    151, 160, 137, 91, 90, 15, 131, 13, 201, 95, 96, 53, 194, 233, 7, 225,
    140, 36, 103, 30, 69, 142, 8, 99, 37, 240, 21, 10, 23, 190, 6, 148,
    247, 120, 234, 75, 0, 26, 197, 62, 94, 252, 219, 203, 117, 35, 11, 32,
    57, 177, 33, 88, 237, 149, 56, 87, 174, 20, 125, 136, 171, 168, 68, 175,
    74, 165, 71, 134, 139, 48, 27, 166, 77, 146, 158, 231, 83, 111, 229, 122,
    60, 211, 133, 230, 220, 105, 92, 41, 55, 46, 245, 40, 244, 102, 143, 54,
    65, 25, 63, 161, 1, 216, 80, 73, 209, 76, 132, 187, 208, 89, 18, 169,
    200, 196, 135, 130, 116, 188, 159, 86, 164, 100, 109, 198, 173, 186, 3, 64,
    52, 217, 226, 250, 124, 123, 5, 202, 38, 147, 118, 126, 255, 82, 85, 212,
    207, 206, 59, 227, 47, 16, 58, 17, 182, 189, 28, 42, 223, 183, 170, 213,
    119, 248, 152, 2, 44, 154, 163, 70, 221, 153, 101, 155, 167, 43, 172, 9,
    129, 22, 39, 253, 19, 98, 108, 110, 79, 113, 224, 232, 178, 185, 112, 104,
    218, 246, 97, 228, 251, 34, 242, 193, 238, 210, 144, 12, 191, 179, 162, 241,
    81, 51, 145, 235, 249, 14, 239, 107, 49, 192, 214, 31, 181, 199, 106, 157,
    184, 84, 204, 176, 115, 121, 50, 45, 127, 4, 150, 254, 138, 236, 205, 93,
    222, 114, 67, 29, 24, 72, 243, 141, 128, 195, 78, 66, 215, 61, 156, 180,
)
_PERM = _PERM_BASE + _PERM_BASE


def _fade(t: float) -> float:
    # 6t^5 - 15t^4 + 10t^3 — Ken Perlin's improved fade curve, C2-
    # continuous so derivatives stay smooth at lattice crossings.
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _grad(hash_val: int, x: float, y: float) -> float:
    # 8-direction 2D gradient via the lower 3 bits. Each branch
    # returns the dot product of the offset (x, y) with one of the
    # eight unit-axis or diagonal gradient vectors.
    h = hash_val & 7
    if h == 0:
        return x + y
    if h == 1:
        return -x + y
    if h == 2:
        return x - y
    if h == 3:
        return -x - y
    if h == 4:
        return x
    if h == 5:
        return -x
    if h == 6:
        return y
    return -y  # h == 7


def pnoise2(x: float, y: float, base: int = 0) -> float:
    """2D Perlin noise sample.

    Returns a float in approximately ``[-1, 1]`` (theoretical bound
    is ``±sqrt(0.5) ~ 0.707`` after fade interpolation; the loose
    ``±1`` bound is what callers actually rely on).

    ``base`` shifts the permutation indexing to produce decorrelated
    patterns for the same ``(x, y)``. The same ``(x, y, base)``
    tuple always returns the same value.

    Output is exactly ``0`` at every integer lattice point.
    """
    xf_floor = math.floor(x)
    yf_floor = math.floor(y)
    xf = x - xf_floor
    yf = y - yf_floor

    # Wrap lattice indices into the 0-255 permutation range.
    # ``base`` shifts the X index so different bases hit different
    # permutation slots — produces decorrelated noise patterns.
    xi = (int(xf_floor) + base) & 0xFF
    yi = int(yf_floor) & 0xFF

    aa = _PERM[_PERM[xi] + yi]
    ab = _PERM[_PERM[xi] + yi + 1]
    ba = _PERM[_PERM[xi + 1] + yi]
    bb = _PERM[_PERM[xi + 1] + yi + 1]

    u = _fade(xf)
    v = _fade(yf)

    g_aa = _grad(aa, xf, yf)
    g_ba = _grad(ba, xf - 1.0, yf)
    g_ab = _grad(ab, xf, yf - 1.0)
    g_bb = _grad(bb, xf - 1.0, yf - 1.0)

    x1 = g_aa + u * (g_ba - g_aa)
    x2 = g_ab + u * (g_bb - g_ab)
    return float(x1 + v * (x2 - x1))

//! 2D Perlin noise — byte-equal port of `nhc/rendering/_perlin.py`.
//!
//! Reproduces Ken Perlin's improved-noise algorithm (2002 paper):
//! cubic-fade interpolation of dot products between offset-from-
//! corner vectors and per-corner pseudo-random gradients selected
//! from an 8-direction set. Output at every integer lattice point
//! is exactly `0.0`. Returns a value in roughly `[-1.0, 1.0]`
//! (theoretical bound `±sqrt(0.5) ~ 0.707`).
//!
//! `f64` throughout — the cross-language gate
//! (`tests/fixtures/perlin/pnoise2_vectors.json`) was generated
//! from the Python `float` reference (which is IEEE 754 f64), and
//! the test asserts exact equality. The `base` parameter shifts
//! the X permutation index so different bases hit decorrelated
//! noise patterns for the same `(x, y)`.

/// Ken Perlin's reference permutation table, from the 2002
/// improved-noise paper. Touching these numbers WITHOUT crossing
/// the cross-language fixture is a determinism break.
const PERM_BASE: [u8; 256] = [
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
];

/// Doubled permutation table — eliminates bounds checks on the
/// second-level lookup (`PERM[PERM[xi] + yi + 1]` can index up to
/// 256 + 255 + 1 = 512, but the high half mirrors the low half).
const PERM: [u16; 512] = {
    let mut p = [0u16; 512];
    let mut i = 0;
    while i < 256 {
        p[i] = PERM_BASE[i] as u16;
        p[i + 256] = PERM_BASE[i] as u16;
        i += 1;
    }
    p
};

/// 6t^5 - 15t^4 + 10t^3 — Ken Perlin's improved fade curve, C2-
/// continuous so derivatives stay smooth at lattice crossings.
#[inline]
fn fade(t: f64) -> f64 {
    t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
}

/// 8-direction 2D gradient via the lower 3 bits. Each branch
/// returns the dot product of the offset `(x, y)` with one of the
/// eight unit-axis or diagonal gradient vectors.
#[inline]
fn grad(hash_val: u16, x: f64, y: f64) -> f64 {
    match hash_val & 7 {
        0 => x + y,
        1 => -x + y,
        2 => x - y,
        3 => -x - y,
        4 => x,
        5 => -x,
        6 => y,
        _ => -y, // h == 7
    }
}

/// 2D Perlin noise sample. Same call shape as the legacy
/// `noise.pnoise2(x, y, base=N)` API: deterministic in `(x, y,
/// base)`, exactly `0.0` at every integer lattice point.
pub fn pnoise2(x: f64, y: f64, base: i32) -> f64 {
    let xf_floor = x.floor();
    let yf_floor = y.floor();
    let xf = x - xf_floor;
    let yf = y - yf_floor;

    // Wrap lattice indices into the 0..=255 permutation range.
    // Two's-complement masking matches Python's infinite-bit
    // `& 0xFF` for negative inputs because Rust's `&` on signed
    // ints operates on the two's-complement representation.
    let xi = ((xf_floor as i32).wrapping_add(base) & 0xFF) as usize;
    let yi = ((yf_floor as i32) & 0xFF) as usize;

    let pxi0 = PERM[xi] as usize;
    let pxi1 = PERM[xi + 1] as usize;
    let aa = PERM[pxi0 + yi];
    let ab = PERM[pxi0 + yi + 1];
    let ba = PERM[pxi1 + yi];
    let bb = PERM[pxi1 + yi + 1];

    let u = fade(xf);
    let v = fade(yf);

    let g_aa = grad(aa, xf, yf);
    let g_ba = grad(ba, xf - 1.0, yf);
    let g_ab = grad(ab, xf, yf - 1.0);
    let g_bb = grad(bb, xf - 1.0, yf - 1.0);

    let x1 = g_aa + u * (g_ba - g_aa);
    let x2 = g_ab + u * (g_bb - g_ab);
    x1 + v * (x2 - x1)
}

#[cfg(test)]
mod tests {
    use super::pnoise2;

    /// Cross-checked against
    /// `tests/fixtures/perlin/pnoise2_vectors.json`. The full 1100-
    /// vector cross-language gate runs from Python via
    /// `tests/unit/test_perlin_vectors.py` once the maturin wheel
    /// is built; these inline vectors give `cargo test` a fast
    /// regression signal independent of the Python harness.
    const FIXTURE_VECTORS: &[(f64, f64, i32, f64)] = &[
        // Integer lattice — algorithm guarantees exact 0.0.
        (-2.0, -2.0, 0, 0.0),
        (-1.0, 0.0, 0, 0.0),
        (0.0, 0.0, 0, 0.0),
        (1.0, 1.0, 0, 0.0),
        // Half-integer points — exactly representable, simple
        // gradient-set values.
        (-1.5, -1.5, 0, 0.375),
        (-1.5, -0.5, 0, 0.5),
        (-0.5, 0.5, 0, 0.125),
        (-0.5, 1.5, 0, 0.375),
        (0.5, -1.5, 11, -0.25),
        // Irrational coordinates — exercise the full f64 mantissa.
        (
            41.539_215_987_362_01,
            46.245_321_679_119_016,
            50,
            -0.143_153_561_080_236_44,
        ),
        (
            -46.547_416_984_865_84,
            -25.726_002_645_693_235,
            1,
            0.263_197_555_216_504_4,
        ),
        (
            40.811_288_519_533_52,
            0.468_685_581_739_023_86,
            0,
            -0.194_255_535_787_769_33,
        ),
        (
            42.434_081_037_539_9,
            -38.654_437_762_456_71,
            77,
            0.059_214_281_278_940_67,
        ),
        (
            6.723_547_686_312_393_5,
            -12.582_518_225_191_109,
            10,
            0.136_495_188_597_218_99,
        ),
    ];

    #[test]
    fn matches_python_fixture_vectors() {
        for &(x, y, base, want) in FIXTURE_VECTORS {
            let got = pnoise2(x, y, base);
            assert_eq!(
                got.to_bits(),
                want.to_bits(),
                "pnoise2({x}, {y}, base={base}) = {got:?} \
                 (bits {:#x}) — want {want:?} (bits {:#x})",
                got.to_bits(),
                want.to_bits(),
            );
        }
    }

    #[test]
    fn integer_lattice_is_zero() {
        for x in -3..=3 {
            for y in -3..=3 {
                let got = pnoise2(x as f64, y as f64, 0);
                assert_eq!(
                    got, 0.0,
                    "pnoise2({x}, {y}, 0) = {got} — expected 0.0"
                );
            }
        }
    }
}

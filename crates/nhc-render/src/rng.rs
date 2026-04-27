//! splitmix64 PRNG.
//!
//! Reference: Sebastiano Vigna, "splitmix64.c" (2015), the
//! state-of-the-art mixing PRNG for seeding the Mersenne-Twister-
//! shaped pipelines that every procedural primitive in this
//! crate uses. Single 64-bit state; one increment + three
//! mix rounds per output. Output is uniform over u64.
//!
//! The Python reference implementation in `nhc/rendering/_perlin.py`
//! and the per-primitive `random.Random(seed)` callers all
//! eventually go through a splitmix64-equivalent mixer, so this
//! module's output is the determinism contract that the IR
//! migration's parity gates lock down. See
//! `tests/fixtures/perlin/pnoise2_vectors.json` (Phase 0.6) for
//! the cross-language vectors.

const GOLDEN_GAMMA: u64 = 0x9e37_79b9_7f4a_7c15;
const MIX_C1: u64 = 0xbf58_476d_1ce4_e5b9;
const MIX_C2: u64 = 0x94d0_49bb_1331_11eb;

/// Stateful splitmix64 generator. Construct from any 64-bit seed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SplitMix64 {
    state: u64,
}

impl SplitMix64 {
    /// Create a generator seeded with `seed`.
    pub const fn from_seed(seed: u64) -> Self {
        Self { state: seed }
    }

    /// Pull the next u64 from the stream.
    ///
    /// Equivalent to Vigna's
    /// ```c
    /// uint64_t next() {
    ///     uint64_t z = (x += 0x9e3779b97f4a7c15);
    ///     z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9;
    ///     z = (z ^ (z >> 27)) * 0x94d049bb133111eb;
    ///     return z ^ (z >> 31);
    /// }
    /// ```
    /// using `wrapping_*` arithmetic for the deliberate u64
    /// overflow semantics.
    pub fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(GOLDEN_GAMMA);
        let mut z = self.state;
        z = (z ^ (z >> 30)).wrapping_mul(MIX_C1);
        z = (z ^ (z >> 27)).wrapping_mul(MIX_C2);
        z ^ (z >> 31)
    }
}

#[cfg(test)]
mod tests {
    use super::SplitMix64;

    /// Cross-checked against Vigna's splitmix64.c reference impl
    /// and against the Python reference in
    /// `tests/unit/test_floor_ir_schema.py` (which runs the same
    /// algorithm in Python and asserts byte-equal output).
    /// Touching these vectors WITHOUT crossing both reference
    /// points is a determinism break.
    const SEED_0_VECTORS: [u64; 8] = [
        0xe220_a839_7b1d_cdaf,
        0x6e78_9e6a_a1b9_65f4,
        0x06c4_5d18_8009_454f,
        0xf88b_b8a8_724c_81ec,
        0x1b39_896a_51a8_749b,
        0x53cb_9f0c_747e_a2ea,
        0x2c82_9abe_1f45_32e1,
        0xc584_133a_c916_ab3c,
    ];

    const SEED_DEADBEEF_VECTORS: [u64; 4] = [
        0x0d7d_9356_0d19_29d2,
        0x491d_fb74_0e50_d43f,
        0x4272_2bf4_473e_5e7d,
        0xd6ca_8a07_90ff_fc45,
    ];

    const SEED_1_VECTORS: [u64; 4] = [
        0x910a_2dec_8902_5cc1,
        0xbeeb_8da1_658e_ec67,
        0xf893_a2ee_fb32_555e,
        0x71c1_8690_ee42_c90b,
    ];

    fn assert_seed_matches(seed: u64, expected: &[u64]) {
        let mut rng = SplitMix64::from_seed(seed);
        for (i, want) in expected.iter().enumerate() {
            let got = rng.next_u64();
            assert_eq!(
                got, *want,
                "splitmix64(seed={seed:#018x}) step {} mismatch: got {:#018x}, want {:#018x}",
                i + 1, got, *want
            );
        }
    }

    #[test]
    fn seed_zero_matches_reference() {
        assert_seed_matches(0, &SEED_0_VECTORS);
    }

    #[test]
    fn seed_deadbeef_matches_reference() {
        assert_seed_matches(0xdead_beef_cafe_babe, &SEED_DEADBEEF_VECTORS);
    }

    #[test]
    fn seed_one_matches_reference() {
        assert_seed_matches(1, &SEED_1_VECTORS);
    }

    #[test]
    fn from_seed_is_const() {
        // Compile-time-evaluable constructor — required for the
        // `static RNG` patterns the primitives modules will use.
        const _R: SplitMix64 = SplitMix64::from_seed(42);
    }
}

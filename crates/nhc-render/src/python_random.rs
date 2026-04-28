//! CPython `random.Random` byte-compat reproduction.
//!
//! The legacy procedural primitives drive `random.Random(seed)`
//! directly, which means every byte-equal parity gate is locked
//! to MT19937 + CPython's seeding + CPython's `random()` /
//! `randint()` / `getrandbits()` glue. This module reproduces
//! those routines in Rust so the procedural primitives can own
//! their RNG without bouncing through Python.
//!
//! Reference points:
//!
//! - MT19937 reference: Matsumoto and Nishimura, 1997. The
//!   `init_genrand` / `init_by_array` seeding routines come from
//!   the same paper.
//! - CPython `_randommodule.c` is the source of truth for the
//!   seed-from-int byte layout (little-endian 32-bit chunks of
//!   `abs(seed)`), the `random()` 53-bit double construction (top
//!   27 bits + top 26 bits → mantissa), and the rejection-sample
//!   `_randbelow` loop.
//!
//! The crate-level splitmix64 in `rng.rs` is for the future
//! structured RNG that lands when Phase 4 cleans up the
//! discrepancies in `design/ir_primitives.md`. That contract is
//! distinct from this module — touching either's vectors without
//! crossing the relevant cross-language gate is a determinism
//! break.

const N: usize = 624;
const M: usize = 397;
const MATRIX_A: u32 = 0x9908_b0df;
const UPPER_MASK: u32 = 0x8000_0000;
const LOWER_MASK: u32 = 0x7fff_ffff;

/// MT19937 state — direct reproduction of the reference C
/// implementation. Holds 624 × 32-bit state words and a cursor.
pub struct MT19937 {
    state: [u32; N],
    index: usize,
}

impl MT19937 {
    /// Reference `init_genrand(s)` — seeds the state from a single
    /// 32-bit value. Used as the bootstrap step for
    /// `init_by_array`; not exposed publicly because CPython never
    /// calls it directly (always goes through `init_by_array`).
    fn init_genrand(s: u32) -> Self {
        let mut state = [0u32; N];
        state[0] = s;
        for i in 1..N {
            let prev = state[i - 1];
            state[i] = 1_812_433_253u32
                .wrapping_mul(prev ^ (prev >> 30))
                .wrapping_add(i as u32);
        }
        Self { state, index: N }
    }

    /// Reference `init_by_array(init_key)` — the seeding routine
    /// CPython reaches via `random.Random(int_seed)`. The key is
    /// the int's absolute value chopped into little-endian 32-bit
    /// chunks; an empty / zero seed still passes a single zero
    /// word so the routine has something to work with.
    pub fn init_by_array(init_key: &[u32]) -> Self {
        let mut mt = Self::init_genrand(19_650_218);
        let key_length = init_key.len();
        let mut i: usize = 1;
        let mut j: usize = 0;
        let mut k = if N > key_length { N } else { key_length };
        while k > 0 {
            let prev = mt.state[i - 1];
            mt.state[i] = (mt.state[i]
                ^ (prev ^ (prev >> 30)).wrapping_mul(1_664_525))
            .wrapping_add(init_key[j])
            .wrapping_add(j as u32);
            i += 1;
            j += 1;
            if i >= N {
                mt.state[0] = mt.state[N - 1];
                i = 1;
            }
            if j >= key_length {
                j = 0;
            }
            k -= 1;
        }
        let mut k = N - 1;
        while k > 0 {
            let prev = mt.state[i - 1];
            mt.state[i] = (mt.state[i]
                ^ (prev ^ (prev >> 30)).wrapping_mul(1_566_083_941))
            .wrapping_sub(i as u32);
            i += 1;
            if i >= N {
                mt.state[0] = mt.state[N - 1];
                i = 1;
            }
            k -= 1;
        }
        // The MSB-1 marker forces the first `next_u32` call to
        // regenerate the state — matches the reference impl.
        mt.state[0] = 0x8000_0000;
        mt.index = N;
        mt
    }

    /// Seed from a Python `int` value. CPython's
    /// `random.Random(seed)` for a positive int packs `abs(seed)`
    /// as little-endian 32-bit chunks; zero collapses to a single
    /// `[0]` chunk so `init_by_array` still has a key to walk.
    pub fn from_python_int_seed(seed: u64) -> Self {
        if seed == 0 {
            return Self::init_by_array(&[0]);
        }
        let bits = 64 - seed.leading_zeros();
        let keymax = (((bits + 31) / 32).max(1)) as usize;
        let mut init_key: Vec<u32> = Vec::with_capacity(keymax);
        for i in 0..keymax {
            init_key.push((seed >> (32 * i)) as u32);
        }
        Self::init_by_array(&init_key)
    }

    /// Refill the 624-word state when the cursor reaches the end.
    fn generate(&mut self) {
        for i in 0..(N - M) {
            let y = (self.state[i] & UPPER_MASK)
                | (self.state[i + 1] & LOWER_MASK);
            self.state[i] = self.state[i + M]
                ^ (y >> 1)
                ^ if y & 1 != 0 { MATRIX_A } else { 0 };
        }
        for i in (N - M)..(N - 1) {
            let y = (self.state[i] & UPPER_MASK)
                | (self.state[i + 1] & LOWER_MASK);
            self.state[i] = self.state[i + M - N]
                ^ (y >> 1)
                ^ if y & 1 != 0 { MATRIX_A } else { 0 };
        }
        let y = (self.state[N - 1] & UPPER_MASK)
            | (self.state[0] & LOWER_MASK);
        self.state[N - 1] = self.state[M - 1]
            ^ (y >> 1)
            ^ if y & 1 != 0 { MATRIX_A } else { 0 };
        self.index = 0;
    }

    /// Pull the next 32-bit output (post-tempering).
    pub fn next_u32(&mut self) -> u32 {
        if self.index >= N {
            self.generate();
        }
        let mut y = self.state[self.index];
        self.index += 1;
        y ^= y >> 11;
        y ^= (y << 7) & 0x9d2c_5680;
        y ^= (y << 15) & 0xefc6_0000;
        y ^= y >> 18;
        y
    }
}

/// Byte-compat shim for `random.Random` — only the surface the
/// procedural primitives need. Deliberately narrow: methods that
/// the legacy code never calls (`gauss`, `shuffle`, `choices`'s
/// cumulative-weights path, …) are intentionally absent so the
/// `import random` ban that lands at the end of Phase 4 doesn't
/// re-introduce dependencies through this struct.
pub struct PyRandom {
    mt: MT19937,
}

impl PyRandom {
    /// Construct from a Python-int seed (matches
    /// `random.Random(seed)` for positive ints).
    pub fn from_seed(seed: u64) -> Self {
        Self {
            mt: MT19937::from_python_int_seed(seed),
        }
    }

    /// Reproduce `random.Random.random()` — combine the top 27
    /// bits of one u32 and the top 26 bits of another into a
    /// 53-bit fraction in `[0.0, 1.0)`.
    pub fn random(&mut self) -> f64 {
        let a = (self.mt.next_u32() >> 5) as f64; // top 27 bits
        let b = (self.mt.next_u32() >> 6) as f64; // top 26 bits
        (a * 67_108_864.0 + b) * (1.0 / 9_007_199_254_740_992.0)
    }

    /// Reproduce `random.Random.getrandbits(k)` for `k <= 32`.
    /// The legacy callers in `nhc/rendering/` never need bigger;
    /// extending to multi-word k is a Phase 4 concern.
    pub fn getrandbits(&mut self, k: u32) -> u32 {
        debug_assert!(k > 0 && k <= 32, "k out of supported range");
        self.mt.next_u32() >> (32 - k)
    }

    /// Reproduce `random.Random._randbelow_with_getrandbits(n)` —
    /// rejection-sample `getrandbits(bit_length(n))` until the
    /// result is in `[0, n)`. The retry loop is exactly what makes
    /// parity testing fragile: a one-call drift compounds every
    /// time `n` isn't a power of two.
    fn randbelow(&mut self, n: u32) -> u32 {
        debug_assert!(n > 0, "_randbelow(0) is unreachable");
        // Match Python's `n.bit_length()` exactly. For n=1 the
        // bit length is 1 (not 0), so `getrandbits(1)` runs and
        // rejects half its samples — the legacy code would do the
        // same, and any byte-equal RNG path has to as well.
        let k = 32 - n.leading_zeros();
        loop {
            let r = self.getrandbits(k);
            if r < n {
                return r;
            }
        }
    }

    /// Reproduce `random.Random.randint(a, b)` — uniform integer
    /// in the inclusive range `[a, b]`.
    pub fn randint(&mut self, a: i64, b: i64) -> i64 {
        debug_assert!(b >= a, "randint requires b >= a");
        let width = (b - a + 1) as u32;
        a + self.randbelow(width) as i64
    }
}

#[cfg(test)]
mod tests {
    use super::PyRandom;

    /// Cross-checked against `random.Random(41)` in CPython 3.14.
    /// The first eight `getrandbits(32)` outputs lock down the
    /// MT19937 state machine + the seed-from-int byte layout.
    #[test]
    fn seed_41_mt_stream_matches_cpython() {
        let mut r = PyRandom::from_seed(41);
        let want: [u32; 8] = [
            0x618a_9261,
            0x550c_aef9,
            0x3b10_6980,
            0xfe1b_1434,
            0x2a81_61e5,
            0xe6e9_d6a1,
            0xe9f0_fcf8,
            0x62b8_a158,
        ];
        for (i, w) in want.iter().enumerate() {
            let got = r.getrandbits(32);
            assert_eq!(
                got, *w,
                "step {i}: got {got:#010x}, want {w:#010x}"
            );
        }
    }

    /// Cross-checked against `random.Random(41).random()` in
    /// CPython 3.14. Locks the 53-bit double construction.
    #[test]
    fn seed_41_random_doubles_match_cpython() {
        let mut r = PyRandom::from_seed(41);
        let want: [f64; 8] = [
            0.381_020_689_995_771_43,
            0.230_719_186_310_475_17,
            0.166_036_724_314_135_2,
            0.913_833_434_772_713,
            0.577_939_025_285_932,
            0.690_132_657_315_267_2,
            0.553_059_475_695_984_1,
            0.383_544_063_955_272_85,
        ];
        for (i, w) in want.iter().enumerate() {
            let got = r.random();
            assert_eq!(
                got.to_bits(),
                w.to_bits(),
                "step {i}: got {got:?} (bits {:#x}), want {w:?} \
                 (bits {:#x})",
                got.to_bits(),
                w.to_bits(),
            );
        }
    }

    /// Cross-checked against `random.Random(41).randint(1, 4)` in
    /// CPython 3.14. Locks the rejection-sample retry loop —
    /// step 4 + step 5 hit the rejection branch, so a missing
    /// retry would visibly bias the output.
    #[test]
    fn seed_41_randint_1_4_matches_cpython() {
        let mut r = PyRandom::from_seed(41);
        let want: [i64; 8] = [4, 3, 2, 2, 4, 3, 3, 4];
        for (i, w) in want.iter().enumerate() {
            let got = r.randint(1, 4);
            assert_eq!(got, *w, "step {i}: got {got}, want {w}");
        }
    }
}

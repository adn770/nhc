//! Shared geometry helpers — Catmull-Rom smoothing and friends.
//!
//! Centripetal Catmull-Rom (α=0.5) → cubic Bézier conversion is
//! the load-bearing routine for cave-themed outlines (cave room
//! shadows, cave wall outlines, smoothed cave floor edges). It
//! lives here rather than per-primitive so multiple primitives can
//! share one byte-equal port of `_centripetal_bezier_cps` /
//! `_smooth_closed_path` in `nhc/rendering/_cave_geometry.py`.
//!
//! The Python references use `**0.5` (which compiles down to libm
//! `pow`) for the centripetal alpha; the Rust port uses `powf(0.5)`
//! which routes through the same libm. On a single host both calls
//! resolve to the same `pow` implementation and produce identical
//! f64 outputs — that is the determinism contract this module
//! relies on, and the per-layer parity gate enforces it.

use std::fmt::Write;

/// Centripetal Catmull-Rom → cubic Bézier control points (α=0.5).
///
/// Returns the two interior control points `(c1x, c1y, c2x, c2y)`
/// of the cubic Bézier segment between `p1` and `p2`, given four
/// sequential Catmull-Rom points `p0..p3`. Mirrors
/// `nhc/rendering/_cave_geometry.py:_centripetal_bezier_cps` for
/// the only alpha the legacy code uses (0.5 — eliminates cusps
/// and self-intersections on jittered control points).
pub fn centripetal_bezier_cps(
    p0: (f64, f64),
    p1: (f64, f64),
    p2: (f64, f64),
    p3: (f64, f64),
) -> (f64, f64, f64, f64) {
    const ALPHA: f64 = 0.5;
    const FLOOR: f64 = 1e-6;

    let d01 = (p1.0 - p0.0).hypot(p1.1 - p0.1).powf(ALPHA).max(FLOOR);
    let d12 = (p2.0 - p1.0).hypot(p2.1 - p1.1).powf(ALPHA).max(FLOOR);
    let d23 = (p3.0 - p2.0).hypot(p3.1 - p2.1).powf(ALPHA).max(FLOOR);

    // Tangent at p1 (Barry-Goldman):
    //   m1 = d12 * [(p1-p0)/d01 - (p2-p0)/(d01+d12) + (p2-p1)/d12]
    let m1x = d12
        * ((p1.0 - p0.0) / d01
            - (p2.0 - p0.0) / (d01 + d12)
            + (p2.0 - p1.0) / d12);
    let m1y = d12
        * ((p1.1 - p0.1) / d01
            - (p2.1 - p0.1) / (d01 + d12)
            + (p2.1 - p1.1) / d12);
    // Tangent at p2:
    //   m2 = d12 * [(p2-p1)/d12 - (p3-p1)/(d12+d23) + (p3-p2)/d23]
    let m2x = d12
        * ((p2.0 - p1.0) / d12
            - (p3.0 - p1.0) / (d12 + d23)
            + (p3.0 - p2.0) / d23);
    let m2y = d12
        * ((p2.1 - p1.1) / d12
            - (p3.1 - p1.1) / (d12 + d23)
            + (p3.1 - p2.1) / d23);

    let c1x = p1.0 + m1x / 3.0;
    let c1y = p1.1 + m1y / 3.0;
    let c2x = p2.0 - m2x / 3.0;
    let c2y = p2.1 - m2y / 3.0;
    (c1x, c1y, c2x, c2y)
}

/// Closed centripetal Catmull-Rom curve → SVG `<path>` element.
///
/// Mirrors `_cave_geometry.py:_smooth_closed_path`. The output
/// is `<path d="M... C... C... ... Z"/>` — caller wraps with
/// fill / stroke / transform attributes as needed.
///
/// Coordinates format with `{:.1}` (one decimal place). Both
/// Python's `f"{x:.1f}"` and Rust's `{:.1}` use round-half-to-
/// even on f64, so for the inputs the cave-geometry pipeline
/// produces (post-jitter, all clean f64) the formatted strings
/// match bit-for-bit.
pub fn smooth_closed_path(coords: &[(f64, f64)]) -> String {
    let n = coords.len();
    debug_assert!(n >= 3, "smooth_closed_path needs >= 3 points");
    let mut s = format!("M{:.1},{:.1}", coords[0].0, coords[0].1);
    for i in 0..n {
        // Python uses `(i - 1) % n` which is non-negative
        // (Python modulo always matches the divisor's sign).
        // `(i + n - 1) % n` is the equivalent for non-negative i.
        let p0 = coords[(i + n - 1) % n];
        let p1 = coords[i];
        let p2 = coords[(i + 1) % n];
        let p3 = coords[(i + 2) % n];
        let (c1x, c1y, c2x, c2y) = centripetal_bezier_cps(p0, p1, p2, p3);
        write!(
            s,
            " C{c1x:.1},{c1y:.1} {c2x:.1},{c2y:.1} {:.1},{:.1}",
            p2.0, p2.1
        )
        .unwrap();
    }
    s.push_str(" Z");
    format!("<path d=\"{s}\"/>")
}

#[cfg(test)]
mod tests {
    use super::{centripetal_bezier_cps, smooth_closed_path};

    /// Cross-checked against
    /// `nhc.rendering._cave_geometry._centripetal_bezier_cps` in
    /// CPython 3.14 with the same four-point inputs. Locks the
    /// `**0.5` / `powf(0.5)` parity contract — if libm's `pow`
    /// diverges between Python and Rust on this host, this test
    /// fails before the SVG fixture parity gate notices.
    #[test]
    fn cps_matches_python_reference() {
        let (c1x, c1y, c2x, c2y) = centripetal_bezier_cps(
            (0.0, 0.0),
            (10.0, 0.0),
            (20.0, 5.0),
            (30.0, 5.0),
        );
        // Captured from CPython 3.14:
        //   from nhc.rendering._cave_geometry import \
        //     _centripetal_bezier_cps
        //   _centripetal_bezier_cps((0,0),(10,0),(20,5),(30,5))
        //   → (13.431618503325588, 0.8100952396309268,
        //      16.568381496674412, 4.189904760369073)
        assert_eq!(c1x.to_bits(), 13.431_618_503_325_588_f64.to_bits());
        assert_eq!(c1y.to_bits(), 0.810_095_239_630_926_8_f64.to_bits());
        assert_eq!(c2x.to_bits(), 16.568_381_496_674_412_f64.to_bits());
        assert_eq!(c2y.to_bits(), 4.189_904_760_369_073_f64.to_bits());
    }

    #[test]
    fn smooth_closed_emits_path_envelope() {
        // Triangle through three corners — confirm output has the
        // right envelope shape (M..C..C..C.. Z) and matches the
        // documented `<path d="..."/>` format.
        let svg = smooth_closed_path(&[
            (0.0, 0.0),
            (10.0, 0.0),
            (5.0, 8.0),
        ]);
        assert!(svg.starts_with("<path d=\"M0.0,0.0 C"));
        assert!(svg.ends_with(" Z\"/>"));
        let cubic_count = svg.matches(" C").count();
        assert_eq!(cubic_count, 3, "one Bézier segment per vertex");
    }
}

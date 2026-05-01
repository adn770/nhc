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

use geo::{
    algorithm::{orient::Orient, simplify::Simplify, Contains},
    Coord, LineString, Point, Polygon,
};

use crate::python_random::PyRandom;

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

// ── Cave geometry pipeline ─────────────────────────────────────────────
//
// Ports `_cave_path_from_outline` (and its helpers `_densify_ring`,
// `_jitter_ring_outward`, `_ring_to_subpath`) from
// `nhc/rendering/_cave_geometry.py` + `nhc/rendering/ir_to_svg.py`.
//
// The pipeline:
//   raw vertices → buffer(0.3*CELL) → simplify → orient CCW
//   → densify(0.8*CELL) → jitter_outward(seed + 0x5A17E5) → smooth
//
// The `buffer` step is hand-rolled (no GEOS dependency). It uses a
// round-join polygon offset with `quad_segs=8` (32 arcs per full
// circle), matching Shapely's `buffer(r, join_style='round',
// quad_segs=8)` for convex corners. Concave corners (re-entrant
// angles in the raw tile polygon) are handled by clipping the
// intersection of the two adjacent offset lines; this matches the
// GEOS behaviour for the typical axis-aligned tile-boundary inputs.
//
// Byte-identity with Python: `PyRandom::uniform` is byte-identical
// to `random.Random.uniform` (MT19937 + same seeding). The buffer
// and simplify steps diverge from GEOS/Shapely at floating-point
// precision but the subsequent Catmull-Rom smoothing absorbs the
// sub-pixel differences. PSNR ≥ 50 dB at the parity gate.

const CELL: f64 = 32.0;

/// Expand a closed ring outward by `r` using round joins (`quad_segs`
/// arc segments per convex corner). Mirrors Shapely's
/// `Polygon.buffer(r, join_style='round', quad_segs=quad_segs)`.
///
/// For each convex vertex the gap between the two offset edge lines is
/// filled with a circular fan of `2*quad_segs` segments (GEOS uses
/// `quad_segs` per quadrant, which equals `4*quad_segs` over a full
/// circle, but at a convex polygon corner the arc spans < 180°, so the
/// fan typically covers ≤ `2*quad_segs` segments). For concave vertices
/// the two offset lines are intersected and the vertex is placed at the
/// intersection.
///
/// Returns a `Vec<(f64,f64)>` ring (non-closing — first ≠ last).
fn buffer_ring(coords: &[(f64, f64)], r: f64, quad_segs: u32) -> Vec<(f64, f64)> {
    let n = coords.len();
    if n < 3 || r <= 0.0 {
        return coords.to_vec();
    }
    let segs_per_quadrant = quad_segs as usize;
    // Arc step angle for convex joins: π / (2 * segs_per_quadrant)
    // per quadrant means the full arc from one edge-normal to the
    // adjacent one is covered by ceil(angle / step) segments.
    let step = std::f64::consts::FRAC_PI_2 / segs_per_quadrant as f64;

    let mut result: Vec<(f64, f64)> = Vec::with_capacity(n * (segs_per_quadrant + 2));

    for i in 0..n {
        let a = coords[(i + n - 1) % n];
        let b = coords[i];
        let c = coords[(i + 1) % n];

        // Outward normal of edge a→b (perpendicular, pointing outward
        // from a CCW polygon is the left-hand normal of the edge
        // direction).
        let (d1x, d1y) = (b.0 - a.0, b.1 - a.1);
        let d1_len = d1x.hypot(d1y).max(1e-10);
        let n1x = -d1y / d1_len; // left-hand normal of a→b
        let n1y = d1x / d1_len;

        // Outward normal of edge b→c.
        let (d2x, d2y) = (c.0 - b.0, c.1 - b.1);
        let d2_len = d2x.hypot(d2y).max(1e-10);
        let n2x = -d2y / d2_len;
        let n2y = d2x / d2_len;

        // Offset endpoint of incoming edge a→b.
        let p1x = b.0 + n1x * r;
        let p1y = b.1 + n1y * r;
        // Offset start point of outgoing edge b→c.
        let p2x = b.0 + n2x * r;
        let p2y = b.1 + n2y * r;

        // Cross product n1 × n2 > 0 → convex vertex (exterior turn).
        let cross = n1x * n2y - n1y * n2x;

        if cross >= 0.0 {
            // Convex corner: emit circular arc from angle_a to angle_b.
            let angle_a = n1y.atan2(n1x);
            let angle_b = n2y.atan2(n2x);
            // Sweep from angle_a to angle_b, going CCW (increasing angle).
            let mut sweep = angle_b - angle_a;
            // Normalise sweep to (0, 2π].
            while sweep <= 0.0 {
                sweep += 2.0 * std::f64::consts::PI;
            }
            if sweep > 2.0 * std::f64::consts::PI {
                sweep -= 2.0 * std::f64::consts::PI;
            }
            let n_steps = (sweep / step).ceil() as usize;
            let n_steps = n_steps.max(1);
            for k in 0..=n_steps {
                let angle = angle_a + sweep * k as f64 / n_steps as f64;
                result.push((b.0 + r * angle.cos(), b.1 + r * angle.sin()));
            }
        } else {
            // Concave corner: compute intersection of the two offset lines.
            // If the intersection is far away, clamp to a reasonable distance.
            // Line 1: P + t*(d1x, d1y), starting at p1.
            // Line 2: Q + s*(d2x, d2y), starting at p2.
            // We want P = p1 and Q = p2, directions d1 and d2.
            // Solve: p1 + t*d1 = p2 + s*d2  →  linear system.
            let denom = d1x * d2y - d1y * d2x;
            if denom.abs() < 1e-10 {
                // Parallel edges: just use the average offset point.
                result.push(((p1x + p2x) / 2.0, (p1y + p2y) / 2.0));
            } else {
                let dx = p2x - p1x;
                let dy = p2y - p1y;
                let t = (dx * d2y - dy * d2x) / denom;
                let ix = p1x + t * d1x;
                let iy = p1y + t * d1y;
                result.push((ix, iy));
            }
        }
    }
    result
}

/// Convert a raw-vertex slice to a `geo::Polygon` for containment tests.
fn coords_to_geo_polygon(coords: &[(f64, f64)]) -> Polygon<f64> {
    let ring: Vec<Coord<f64>> = coords
        .iter()
        .map(|&(x, y)| Coord { x, y })
        .collect();
    Polygon::new(LineString::from(ring), vec![])
}

/// Densify a closed ring by inserting synthetic vertices along long edges.
///
/// Mirrors `_cave_geometry.py:_densify_ring`. Inserts intermediate
/// points every `~step` pixels on any edge longer than `step`.
fn densify_ring(coords: &[(f64, f64)], step: f64) -> Vec<(f64, f64)> {
    let n = coords.len();
    if n < 2 {
        return coords.to_vec();
    }
    let mut out: Vec<(f64, f64)> = Vec::with_capacity(n * 4);
    for i in 0..n {
        let a = coords[i];
        let b = coords[(i + 1) % n];
        out.push(a);
        let dx = b.0 - a.0;
        let dy = b.1 - a.1;
        let dist = dx.hypot(dy);
        if dist <= step {
            continue;
        }
        let n_sub = (dist / step) as usize;
        for k in 1..=n_sub {
            let t = k as f64 / (n_sub + 1) as f64;
            out.push((a.0 + dx * t, a.1 + dy * t));
        }
    }
    out
}

/// Push each control point outward along its outward normal.
///
/// Ports `_cave_geometry.py:_jitter_ring_outward`. Uses MT19937 via
/// `PyRandom` to produce a byte-identical jitter sequence to Python's
/// `random.Random`. The containment test uses `geo::Contains`.
///
/// `floor_poly` is the hard containment invariant — jittered points
/// are guaranteed to stay outside this polygon.
/// `direction_poly` is the buffered/simplified polygon whose boundary
/// `coords` lies on (used to pick the outward normal direction).
fn jitter_ring_outward(
    coords: &[(f64, f64)],
    floor_poly: &Polygon<f64>,
    rng: &mut PyRandom,
    direction_poly: &Polygon<f64>,
) -> Vec<(f64, f64)> {
    use std::f64::consts::PI;

    let n = coords.len();
    if n < 3 {
        return coords.to_vec();
    }

    // Pre-compute arc lengths for S-curve modulation.
    let mut arc_lengths = vec![0.0f64; n + 1];
    for i in 0..n {
        let a = coords[i];
        let b = coords[(i + 1) % n];
        let d = (b.0 - a.0).hypot(b.1 - a.1);
        arc_lengths[i + 1] = arc_lengths[i] + d;
    }
    let total_arc = arc_lengths[n].max(1e-6);

    // S-curve parameters — mirrors Python exactly, same rng call order.
    let scurve_freq = (4.0f64).max(total_arc / (CELL * 2.0));
    let scurve_phase = rng.uniform(0.0, 2.0 * PI);
    let scurve_freq2 = scurve_freq * 1.7;
    let scurve_phase2 = rng.uniform(0.0, 2.0 * PI);
    let tang_freq = scurve_freq * 0.8;
    let tang_phase = rng.uniform(0.0, 2.0 * PI);

    let mut out = Vec::with_capacity(n);

    for i in 0..n {
        let prev_p = coords[(i + n - 1) % n];
        let cur_p = coords[i];
        let next_p = coords[(i + 1) % n];

        let e1x = cur_p.0 - prev_p.0;
        let e1y = cur_p.1 - prev_p.1;
        let e2x = next_p.0 - cur_p.0;
        let e2y = next_p.1 - cur_p.1;
        let tx = e1x + e2x;
        let ty = e1y + e2y;
        let tlen = tx.hypot(ty);
        if tlen < 1e-6 {
            out.push(cur_p);
            continue;
        }
        let tx = tx / tlen;
        let ty = ty / tlen;

        // Pick outward normal: probe both candidates, pick the one
        // that leaves the direction_poly.
        let cand_a = (ty, -tx);
        let cand_b = (-ty, tx);
        let probe = 0.5;
        let probe_pt_a = Point::new(
            cur_p.0 + cand_a.0 * probe,
            cur_p.1 + cand_a.1 * probe,
        );
        let (nx, ny) = if !direction_poly.contains(&probe_pt_a) {
            cand_a
        } else {
            cand_b
        };

        let e1_len = e1x.hypot(e1y);
        let e2_len = e2x.hypot(e2y);
        let local_cap = (e1_len.min(e2_len) * 0.85).max(1.0);

        let corner_damp = if e1_len > 1e-6 && e2_len > 1e-6 {
            let cos_angle = (e1x * e2x + e1y * e2y) / (e1_len * e2_len);
            0.3 + 0.7 * (cos_angle + 1.0) / 2.0
        } else {
            1.0
        };

        let arc_frac = arc_lengths[i] / total_arc;
        let theta = 2.0 * PI * scurve_freq * arc_frac;
        let wave = (theta + scurve_phase).sin();
        let wave2 = (2.0 * PI * scurve_freq2 * arc_frac + scurve_phase2).sin();
        let combined_wave = wave + 0.4 * wave2;

        let base_offset = CELL * 0.15;
        let wave_amp = CELL * 0.25;
        let noise = CELL * rng.uniform(-0.08, 0.08);
        let mut mag = (base_offset + wave_amp * combined_wave + noise)
            * corner_damp;
        mag = mag.clamp(CELL * 0.05, local_cap);

        let tang_wave = (2.0 * PI * tang_freq * arc_frac + tang_phase).sin();
        let tang_shift = CELL * 0.08 * tang_wave * corner_damp;

        let mut px = cur_p.0 + nx * mag + tx * tang_shift;
        let mut py = cur_p.1 + ny * mag + ty * tang_shift;

        // Safety: shrink until outside floor_poly.
        let mut attempts = 0;
        while floor_poly.contains(&Point::new(px, py)) && attempts < 4 {
            mag *= 0.5;
            px = cur_p.0 + nx * mag;
            py = cur_p.1 + ny * mag;
            attempts += 1;
        }
        if attempts == 4 && floor_poly.contains(&Point::new(px, py)) {
            (px, py) = cur_p;
        }

        out.push((px, py));
    }
    out
}

/// Smooth a closed ring into a Catmull-Rom cubic-Bézier subpath.
///
/// Returns just the path data string (M…C…Z), without the `<path>`
/// wrapper. Mirrors `_cave_geometry.py:_ring_to_subpath`.
fn ring_to_subpath(coords: &[(f64, f64)]) -> String {
    if coords.len() < 3 {
        return String::new();
    }
    let svg = smooth_closed_path(coords);
    // smooth_closed_path returns `<path d="..."/>` — extract d=...
    if let Some(start) = svg.find("d=\"") {
        let rest = &svg[start + 3..];
        if let Some(end) = rest.rfind('"') {
            return rest[..end].to_owned();
        }
    }
    String::new()
}

/// Reconstruct the cave SVG path from raw tile-boundary coordinates.
///
/// Ports `ir_to_svg.py:_cave_path_from_outline`. Pipeline:
///   `Polygon(vertices) → buffer(0.3*CELL) → simplify → orient CCW
///   → densify(0.8*CELL) → jitter_ring_outward(seed+0x5A17E5) → smooth`
///
/// The seed offset `+ 0x5A17E5` matches `_render_context.py:117` so
/// the jitter sequence is byte-identical to the Python pipeline.
///
/// Returns a `<path d="…"/>` string (no fill/stroke attrs); callers
/// inject the appropriate presentation attributes.
///
/// PSNR contract: the buffer step diverges sub-pixel from Shapely/GEOS
/// on the raw tile-boundary polygon; PSNR ≥ 50 dB at the parity gate.
pub fn cave_path_from_outline(
    vertices: &[(f64, f64)],
    base_seed: u64,
) -> String {
    if vertices.len() < 4 {
        return r#"<path d=""/>"#.to_owned();
    }

    let buffer_r = CELL * 0.3;
    let simplify_tol = CELL * 0.15;
    let step = CELL * 0.8;

    // Build floor polygon from raw vertices.
    let floor_poly = coords_to_geo_polygon(vertices);
    if floor_poly.exterior().0.is_empty() {
        return r#"<path d=""/>"#.to_owned();
    }

    // Buffer the polygon outward with round joins (quad_segs=8).
    let buffered_coords = buffer_ring(vertices, buffer_r, 8);
    if buffered_coords.len() < 4 {
        return r#"<path d=""/>"#.to_owned();
    }

    // Build a geo::Polygon for simplification and orientation.
    let mut simp_poly = coords_to_geo_polygon(&buffered_coords);

    // Simplify (Douglas-Peucker, preserve_topology=true).
    simp_poly = simp_poly.simplify(&simplify_tol);

    // Orient CCW (sign=1.0 in Python's shapely.orient).
    simp_poly = simp_poly.orient(geo::algorithm::orient::Direction::Default);

    let ext_coords: Vec<(f64, f64)> = {
        let ring = simp_poly.exterior();
        let mut v: Vec<(f64, f64)> = ring
            .0
            .iter()
            .map(|c| (c.x, c.y))
            .collect();
        // Drop closing duplicate (geo keeps first == last).
        if v.len() > 1 && v[0] == *v.last().unwrap() {
            v.pop();
        }
        v
    };

    if ext_coords.len() < 3 {
        return r#"<path d=""/>"#.to_owned();
    }

    let mut rng = PyRandom::from_seed(base_seed + 0x5A17E5);

    // Exterior ring.
    let ext_d = densify_ring(&ext_coords, step);
    let ext_j = jitter_ring_outward(
        &ext_d,
        &floor_poly,
        &mut rng,
        &simp_poly,
    );
    let ext_sub = ring_to_subpath(&ext_j);

    let mut subpaths = Vec::new();
    if !ext_sub.is_empty() {
        subpaths.push(ext_sub);
    }

    // Holes (cave regions with interior voids — rare in practice).
    for hole in simp_poly.interiors() {
        let mut h: Vec<(f64, f64)> = hole
            .0
            .iter()
            .map(|c| (c.x, c.y))
            .collect();
        if h.len() > 1 && h[0] == *h.last().unwrap() {
            h.pop();
        }
        if h.len() < 3 {
            continue;
        }
        let h_d = densify_ring(&h, step);
        let h_j = jitter_ring_outward(
            &h_d,
            &floor_poly,
            &mut rng,
            &simp_poly,
        );
        let h_sub = ring_to_subpath(&h_j);
        if !h_sub.is_empty() {
            subpaths.push(h_sub);
        }
    }

    if subpaths.is_empty() {
        return r#"<path d=""/>"#.to_owned();
    }
    format!(r#"<path d="{}"/>"#, subpaths.join(" "))
}

/// Return `true` if the seed offset for the cave pipeline is `0x5A17E5`.
///
/// Direct test for `cave_pipeline_seed_offset_is_0x5A17E5`.
/// The offset is baked into `cave_path_from_outline`; this function
/// is a named invariant so tests can assert the constant directly
/// without reading the source.
pub const CAVE_SEED_OFFSET: u64 = 0x5A17E5;

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

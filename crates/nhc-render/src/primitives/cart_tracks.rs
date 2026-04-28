//! Cart-tracks decorator — Phase 4, sub-step 11 (plan §8 Q2).
//!
//! Reproduces ``CART_TRACK_RAILS`` (two parallel rails per
//! TRACK tile) and ``CART_TRACK_TIES`` (single cross-tie per
//! TRACK tile) from ``nhc/rendering/_floor_detail.py``. Both
//! decorators share the same predicate; orientation per tile
//! comes from the IR's pre-resolved
//! ``CartTracksVariant.is_horizontal[]`` parallel array
//! (legacy ``_track_horizontal_at`` looks at the east / west
//! neighbours for TRACK adjacency — the emitter lifts that
//! check so the consumer doesn't need level access).
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required. RNG-free painters
//! (geometry is fully determined by tile + orientation).

const CELL: f64 = 32.0;
const TRACK_RAIL: &str = "#6A5A4A";
const TRACK_TIE: &str = "#8A7A5A";

pub fn draw_cart_tracks(
    tiles: &[(i32, i32, bool)], _seed: u64,
) -> Vec<String> {
    if tiles.is_empty() {
        return Vec::new();
    }
    let mut rails: Vec<String> = Vec::new();
    let mut ties: Vec<String> = Vec::new();

    for &(x, y, horizontal) in tiles {
        let px = f64::from(x) * CELL;
        let py = f64::from(y) * CELL;
        let cx = px + CELL / 2.0;
        let cy = py + CELL / 2.0;
        if horizontal {
            let y1 = py + CELL * 0.35;
            let y2 = py + CELL * 0.65;
            rails.push(format!(
                "<line x1=\"{px:.1}\" y1=\"{y1:.1}\" \
                 x2=\"{:.1}\" y2=\"{y1:.1}\"/>",
                px + CELL,
            ));
            rails.push(format!(
                "<line x1=\"{px:.1}\" y1=\"{y2:.1}\" \
                 x2=\"{:.1}\" y2=\"{y2:.1}\"/>",
                px + CELL,
            ));
            ties.push(format!(
                "<line x1=\"{cx:.1}\" y1=\"{:.1}\" \
                 x2=\"{cx:.1}\" y2=\"{:.1}\"/>",
                y1 - 1.0,
                y2 + 1.0,
            ));
        } else {
            let x1 = px + CELL * 0.35;
            let x2 = px + CELL * 0.65;
            rails.push(format!(
                "<line x1=\"{x1:.1}\" y1=\"{py:.1}\" \
                 x2=\"{x1:.1}\" y2=\"{:.1}\"/>",
                py + CELL,
            ));
            rails.push(format!(
                "<line x1=\"{x2:.1}\" y1=\"{py:.1}\" \
                 x2=\"{x2:.1}\" y2=\"{:.1}\"/>",
                py + CELL,
            ));
            ties.push(format!(
                "<line x1=\"{:.1}\" y1=\"{cy:.1}\" \
                 x2=\"{:.1}\" y2=\"{cy:.1}\"/>",
                x1 - 1.0,
                x2 + 1.0,
            ));
        }
    }

    let mut out: Vec<String> = Vec::new();
    if !rails.is_empty() {
        out.push(format!(
            "<g id=\"cart-tracks\" opacity=\"0.55\" \
             stroke=\"{TRACK_RAIL}\" stroke-width=\"0.9\" \
             stroke-linecap=\"round\">{}</g>",
            rails.concat(),
        ));
    }
    if !ties.is_empty() {
        out.push(format!(
            "<g id=\"cart-track-ties\" opacity=\"0.5\" \
             stroke=\"{TRACK_TIE}\" stroke-width=\"1.4\" \
             stroke-linecap=\"round\">{}</g>",
            ties.concat(),
        ));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_tiles_returns_empty() {
        assert!(draw_cart_tracks(&[], 0).is_empty());
    }

    #[test]
    fn horizontal_tile_emits_rails_and_tie() {
        let out = draw_cart_tracks(&[(0, 0, true)], 0);
        assert_eq!(out.len(), 2);
        assert!(out[0].contains("cart-tracks"));
        assert!(out[1].contains("cart-track-ties"));
    }

    #[test]
    fn vertical_tile_orientation() {
        let h = &draw_cart_tracks(&[(0, 0, true)], 0)[0];
        let v = &draw_cart_tracks(&[(0, 0, false)], 0)[0];
        assert_ne!(h, v, "horizontal vs vertical should differ");
    }
}

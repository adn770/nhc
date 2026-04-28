//! Tiny SVG-path subset parser — `M x,y L x,y M x,y ...`.
//!
//! The IR's procedural primitives emit pre-formatted SVG path
//! `d=` strings as the FFI return shape; the PNG handlers parse
//! those back into `tiny-skia::Path` move/line ops rather than
//! sharing a Path type across the FFI boundary. The surface
//! covers the legacy primitives' output (M / L commands only,
//! coordinates `f32`-precision); curve commands belong to the
//! cave-shadow / surface-feature handlers, which build their
//! `Path` directly from the structured polygon.

use tiny_skia::PathBuilder;

/// Parse `s` into a `tiny-skia::Path`. Tokens are whitespace-
/// separated; each token starts with `M` or `L` and carries an
/// `x,y` pair. Unknown tokens are skipped silently to keep the
/// parser robust against future emitter changes that don't
/// touch the rendering primitives.
pub fn parse_path_d(s: &str) -> Option<tiny_skia::Path> {
    let mut pb = PathBuilder::new();
    let mut any = false;
    for tok in s.split_whitespace() {
        if let Some(rest) = tok.strip_prefix('M') {
            if let Some((x, y)) = parse_xy(rest) {
                pb.move_to(x, y);
                any = true;
            }
        } else if let Some(rest) = tok.strip_prefix('L') {
            if let Some((x, y)) = parse_xy(rest) {
                pb.line_to(x, y);
                any = true;
            }
        }
    }
    if !any {
        return None;
    }
    pb.finish()
}

/// `"x,y"` → `(x, y)`. Accepts whitespace either side of the
/// comma.
pub fn parse_xy(s: &str) -> Option<(f32, f32)> {
    let s = s.trim();
    let comma = s.find(',')?;
    let x: f32 = s[..comma].trim().parse().ok()?;
    let y: f32 = s[comma + 1..].trim().parse().ok()?;
    Some((x, y))
}

#[cfg(test)]
mod tests {
    use super::{parse_path_d, parse_xy};

    #[test]
    fn parse_xy_handles_integer_coords() {
        assert_eq!(parse_xy("32,64"), Some((32.0, 64.0)));
    }

    #[test]
    fn parse_xy_handles_decimal_coords() {
        assert_eq!(parse_xy("12.5,7.25"), Some((12.5, 7.25)));
    }

    #[test]
    fn parse_xy_handles_whitespace() {
        assert_eq!(parse_xy("  3.0 ,  4.5  "), Some((3.0, 4.5)));
    }

    #[test]
    fn parse_xy_rejects_garbage() {
        assert!(parse_xy("not-a-pair").is_none());
        assert!(parse_xy("3").is_none());
    }

    #[test]
    fn parse_path_d_handles_single_move_line() {
        let p = parse_path_d("M0,0 L32,0").unwrap();
        // PathBuilder produces a non-empty Path; tiny-skia
        // doesn't expose a public command-iterator surface, so
        // we settle for a smoke check on bounds.
        let bounds = p.bounds();
        assert!(bounds.width() >= 32.0);
    }

    #[test]
    fn parse_path_d_handles_multi_subpath() {
        let p = parse_path_d("M0,0 L10,0 M0,10 L10,10").unwrap();
        // Two subpaths combine into one Path.
        let bounds = p.bounds();
        assert!(bounds.height() >= 10.0);
    }

    #[test]
    fn parse_path_d_returns_none_on_empty() {
        assert!(parse_path_d("").is_none());
        assert!(parse_path_d("not-a-path").is_none());
    }
}

//! Tiny SVG-path subset parser — `M x,y`, `L x,y`,
//! `C c1x,c1y c2x,c2y x,y`, `Z`.
//!
//! The IR's procedural primitives emit pre-formatted SVG path
//! `d=` strings as the FFI return shape; the PNG handlers parse
//! those back into `tiny-skia::Path` move/line/curve/close ops
//! rather than sharing a Path type across the FFI boundary.
//!
//! The cave-region wall outline (Phase 5.5) drives the C-curve
//! support: the legacy emitter writes M/C/Z command sequences
//! at `:.1` precision per Catmull-Rom subpath, and the
//! rasteriser replays each one as a `cubic_to`. Other layers
//! still go through `M / L` only.

use tiny_skia::PathBuilder;

/// Parse `s` into a `tiny-skia::Path`. Walks tokens left-to-
/// right; each token either kicks off a new command (M / L /
/// C / Z) or supplies coordinate pairs that the running command
/// consumes. Unknown commands skip the token.
pub fn parse_path_d(s: &str) -> Option<tiny_skia::Path> {
    let mut pb = PathBuilder::new();
    let mut any = false;
    let mut tokens = s.split_whitespace().peekable();
    let mut last = (0.0_f32, 0.0_f32);
    while let Some(tok) = tokens.next() {
        match command_letter(tok) {
            Some('M') => {
                if let Some((x, y)) = parse_xy(strip_command(tok, 'M')) {
                    pb.move_to(x, y);
                    last = (x, y);
                    any = true;
                }
            }
            Some('L') => {
                if let Some((x, y)) = parse_xy(strip_command(tok, 'L')) {
                    pb.line_to(x, y);
                    last = (x, y);
                    any = true;
                }
            }
            Some('C') => {
                let p1 = parse_xy(strip_command(tok, 'C'));
                let p2 = tokens.next().and_then(parse_xy);
                let p3 = tokens.next().and_then(parse_xy);
                if let (Some((c1x, c1y)), Some((c2x, c2y)), Some((x, y))) =
                    (p1, p2, p3)
                {
                    pb.cubic_to(c1x, c1y, c2x, c2y, x, y);
                    last = (x, y);
                    any = true;
                }
            }
            Some('Z') | Some('z') => {
                pb.close();
                // Spec: after a close, the pen returns to the
                // last move-to point. We approximate that by
                // leaving `last` untouched — for the legacy
                // emitter's M-then-Cs-then-Z shape this is the
                // same point.
            }
            _ => {}
        }
    }
    let _ = last; // reserved for future relative-command support
    if !any {
        return None;
    }
    pb.finish()
}

fn command_letter(tok: &str) -> Option<char> {
    let c = tok.chars().next()?;
    match c {
        'M' | 'L' | 'C' | 'Z' | 'z' => Some(c),
        _ => None,
    }
}

fn strip_command(tok: &str, letter: char) -> &str {
    tok.strip_prefix(letter).unwrap_or(tok)
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
        let bounds = p.bounds();
        assert!(bounds.width() >= 32.0);
    }

    #[test]
    fn parse_path_d_handles_multi_subpath() {
        let p = parse_path_d("M0,0 L10,0 M0,10 L10,10").unwrap();
        let bounds = p.bounds();
        assert!(bounds.height() >= 10.0);
    }

    #[test]
    fn parse_path_d_returns_none_on_empty() {
        assert!(parse_path_d("").is_none());
        assert!(parse_path_d("not-a-path").is_none());
    }

    /// Cave-region shape — M/C/Z subpath with 3 cubic segments.
    #[test]
    fn parse_path_d_handles_cubic_segments() {
        let d = "M0.0,0.0 C5.0,0.0 10.0,5.0 10.0,10.0 \
                 C10.0,15.0 5.0,20.0 0.0,20.0 \
                 C-5.0,15.0 -5.0,5.0 0.0,0.0 Z";
        let p = parse_path_d(d).unwrap();
        let bounds = p.bounds();
        assert!(bounds.width() >= 10.0);
        assert!(bounds.height() >= 20.0);
    }
}

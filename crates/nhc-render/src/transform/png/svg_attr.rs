//! Tiny SVG attribute parser — extracts `name="value"` pairs.
//!
//! The Phase 4 RNG-heavy primitives (`hatch`, `floor_detail`,
//! `thematic_detail`, the seven decorators, and the surface
//! features) all return pre-formatted SVG fragments. The PNG
//! handlers replay those fragments by extracting the relevant
//! attributes and feeding them into `tiny-skia`.
//!
//! The parser is deliberately small — no namespace handling, no
//! escape decoding, no nested elements. The legacy emitter
//! produces single-element fragments with simple attributes;
//! anything fancier than that lives in primitives that build
//! their `tiny-skia::Path` directly (see `shadow.rs`).

/// Find the value of `name="..."` in `s`. Returns `None` if the
/// attribute isn't present or its value isn't terminated by `"`.
pub fn extract_attr<'a>(s: &'a str, name: &str) -> Option<&'a str> {
    // Look for ` name="` (leading space dodges substring hits like
    // `stroke-width` vs `width`).
    let needle = format!(" {name}=\"");
    let start = s.find(&needle)? + needle.len();
    let rest = &s[start..];
    let end = rest.find('"')?;
    Some(&rest[..end])
}

pub fn extract_f32(s: &str, name: &str) -> Option<f32> {
    extract_attr(s, name)?.trim().parse().ok()
}

#[cfg(test)]
mod tests {
    use super::{extract_attr, extract_f32};

    #[test]
    fn extract_attr_finds_simple_value() {
        let s = "<rect x=\"32\" y=\"64\"/>";
        assert_eq!(extract_attr(s, "x"), Some("32"));
        assert_eq!(extract_attr(s, "y"), Some("64"));
    }

    #[test]
    fn extract_attr_disambiguates_overlapping_names() {
        // `width` and `stroke-width` share the suffix; the leading-
        // space match avoids the false positive.
        let s = "<line stroke-width=\"1.5\" width=\"32\"/>";
        assert_eq!(extract_attr(s, "width"), Some("32"));
        assert_eq!(extract_attr(s, "stroke-width"), Some("1.5"));
    }

    #[test]
    fn extract_attr_missing_returns_none() {
        let s = "<rect x=\"32\"/>";
        assert!(extract_attr(s, "fill").is_none());
    }

    #[test]
    fn extract_f32_parses_decimal() {
        let s = "<line stroke-width=\"1.25\"/>";
        assert_eq!(extract_f32(s, "stroke-width"), Some(1.25));
    }

}

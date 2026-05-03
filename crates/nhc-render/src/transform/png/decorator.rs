//! DecoratorOp rasterisation — the structured decorator
//! pipeline the SVG handler at
//! `_draw_decorator_from_ir` walks. Phase 5.4.x lands per-
//! variant branches one at a time; the dispatcher routes each
//! entry through to its `primitives::*::paint_*` Painter-trait
//! port via a single `SkiaPainter` constructed for the dispatch
//! scope.
//!
//! Live variants:
//!
//! - 5.4.1 Cobblestone — 3×3 jittered grid + 12 % stones.
//! - 5.4.2 Brick — 4×2 running-bond layout per tile.
//! - 5.4.3 Flagstone — 4 irregular pentagon plates per tile.
//! - 5.4.4 Opus Romano — 4-stone Versailles tiling, RNG-free.
//! - 5.4.5 Field Stone — 10 % per-tile probabilistic ellipse.
//! - 5.4.6 Cart Tracks — paired rails + cross-tie per tile.
//! - 5.4.7 Ore Deposit — diamond glint per ore-deposit wall tile.
//!
//! Phases 2.13a–2.13g of `plans/nhc_pure_ir_plan.md` port every
//! decorator branch to the Painter trait. As of 2.13g the
//! `paint_fragments` SVG-string round-trip is gone from this
//! dispatcher — every sub-handler runs inside the same
//! `SkiaPainter::with_transform` scope. Other call sites
//! (`bush.rs`, plus a few `transform/png/*` handlers like roof
//! and floor_detail's wood-floor branch) still use
//! `paint_fragments`, so the helper itself stays alive until
//! 2.20 retires the SVG-string emit path crate-wide.

use crate::ir::{DecoratorOp, FloorIR, OpEntry};
use crate::painter::SkiaPainter;
use crate::primitives;

use super::RasterCtx;

pub(super) fn draw(
    entry: &OpEntry<'_>,
    _fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_decorator_op() {
        Some(o) => o,
        None => return,
    };
    let seed = op.seed();

    // Painter-trait dispatch — every decorator branch (Phase 2.13a–g)
    // runs through the same `SkiaPainter`, so the legacy
    // `paint_fragments` SVG-string round-trip is gone from this
    // dispatcher.
    let mut painter = SkiaPainter::with_transform(ctx.pixmap, ctx.transform);
    paint_cobblestone(&op, seed, &mut painter);
    paint_brick(&op, seed, &mut painter);
    paint_flagstone(&op, seed, &mut painter);
    paint_opus_romano(&op, seed, &mut painter);
    paint_field_stone(&op, seed, &mut painter);
    paint_cart_tracks(&op, seed, &mut painter);
    paint_ore_deposit(&op, seed, &mut painter);
}

fn paint_cobblestone(
    op: &DecoratorOp<'_>,
    seed: u64,
    painter: &mut SkiaPainter<'_>,
) {
    let variants = match op.cobblestone() {
        Some(v) => v,
        None => return,
    };
    for variant in variants.iter() {
        let tiles: Vec<(i32, i32)> = variant
            .tiles()
            .map(|t| t.iter().map(|c| (c.x(), c.y())).collect())
            .unwrap_or_default();
        if tiles.is_empty() {
            continue;
        }
        primitives::cobblestone::paint_cobblestone(painter, &tiles, seed);
    }
}

fn paint_brick(
    op: &DecoratorOp<'_>,
    seed: u64,
    painter: &mut SkiaPainter<'_>,
) {
    let variants = match op.brick() {
        Some(v) => v,
        None => return,
    };
    for variant in variants.iter() {
        let tiles: Vec<(i32, i32)> = variant
            .tiles()
            .map(|t| t.iter().map(|c| (c.x(), c.y())).collect())
            .unwrap_or_default();
        if tiles.is_empty() {
            continue;
        }
        primitives::brick::paint_brick(painter, &tiles, seed);
    }
}

fn paint_flagstone(
    op: &DecoratorOp<'_>,
    seed: u64,
    painter: &mut SkiaPainter<'_>,
) {
    let variants = match op.flagstone() {
        Some(v) => v,
        None => return,
    };
    for variant in variants.iter() {
        let tiles: Vec<(i32, i32)> = variant
            .tiles()
            .map(|t| t.iter().map(|c| (c.x(), c.y())).collect())
            .unwrap_or_default();
        if tiles.is_empty() {
            continue;
        }
        primitives::flagstone::paint_flagstone(painter, &tiles, seed);
    }
}

fn paint_opus_romano(
    op: &DecoratorOp<'_>,
    seed: u64,
    painter: &mut SkiaPainter<'_>,
) {
    let variants = match op.opus_romano() {
        Some(v) => v,
        None => return,
    };
    for variant in variants.iter() {
        let tiles: Vec<(i32, i32)> = variant
            .tiles()
            .map(|t| t.iter().map(|c| (c.x(), c.y())).collect())
            .unwrap_or_default();
        if tiles.is_empty() {
            continue;
        }
        primitives::opus_romano::paint_opus_romano(painter, &tiles, seed);
    }
}

fn paint_field_stone(
    op: &DecoratorOp<'_>,
    seed: u64,
    painter: &mut SkiaPainter<'_>,
) {
    let variants = match op.field_stone() {
        Some(v) => v,
        None => return,
    };
    for variant in variants.iter() {
        let tiles: Vec<(i32, i32)> = variant
            .tiles()
            .map(|t| t.iter().map(|c| (c.x(), c.y())).collect())
            .unwrap_or_default();
        if tiles.is_empty() {
            continue;
        }
        primitives::field_stone::paint_field_stone(painter, &tiles, seed);
    }
}

fn paint_cart_tracks(
    op: &DecoratorOp<'_>,
    seed: u64,
    painter: &mut SkiaPainter<'_>,
) {
    let variants = match op.cart_tracks() {
        Some(v) => v,
        None => return,
    };
    for variant in variants.iter() {
        let tiles_v = match variant.tiles() {
            Some(t) => t,
            None => continue,
        };
        let horiz = variant.is_horizontal();
        let tiles: Vec<(i32, i32, bool)> = tiles_v
            .iter()
            .enumerate()
            .map(|(i, c)| {
                let h = horiz.as_ref().map(|v| v.get(i)).unwrap_or(false);
                (c.x(), c.y(), h)
            })
            .collect();
        if tiles.is_empty() {
            continue;
        }
        primitives::cart_tracks::paint_cart_tracks(painter, &tiles, seed);
    }
}

fn paint_ore_deposit(
    op: &DecoratorOp<'_>,
    seed: u64,
    painter: &mut SkiaPainter<'_>,
) {
    let variants = match op.ore_deposit() {
        Some(v) => v,
        None => return,
    };
    for variant in variants.iter() {
        let tiles: Vec<(i32, i32)> = variant
            .tiles()
            .map(|t| t.iter().map(|c| (c.x(), c.y())).collect())
            .unwrap_or_default();
        if tiles.is_empty() {
            continue;
        }
        primitives::ore_deposit::paint_ore_deposit(painter, &tiles, seed);
    }
}

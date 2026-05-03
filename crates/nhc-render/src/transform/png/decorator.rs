//! DecoratorOp rasterisation — the structured decorator
//! pipeline the SVG handler at
//! `_draw_decorator_from_ir` walks. Phase 5.4.x lands per-
//! variant branches one at a time; the dispatcher routes each
//! entry through to its `primitives::*::draw_*` Rust port and
//! the new `fragment::paint_fragments` helper rasterises the
//! returned `<g>` envelopes.
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
//! Phases 2.13a–2.13d of `plans/nhc_pure_ir_plan.md` port the
//! cobblestone, brick, flagstone, and opus_romano branches to the
//! Painter trait. The remaining three sub-handlers stay on the
//! legacy `paint_fragments` SVG-string path until their respective
//! 2.13e–2.13g commits land. To coexist without conflicting
//! `&mut Pixmap` borrows, the `SkiaPainter` is constructed inside
//! a scoped block around the ported variants only — the legacy
//! sub-handlers run AFTER the painter drops, so their
//! `RasterCtx`-based `&mut Pixmap` borrows are unaffected.

use crate::ir::{DecoratorOp, FloorIR, OpEntry};
use crate::painter::SkiaPainter;
use crate::primitives;

use super::fragment::paint_fragments;
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

    // Painter-trait ports (Phase 2.13a–g land one branch at a
    // time). Scope the SkiaPainter to a block so its `&mut Pixmap`
    // borrow drops before the legacy sub-handlers run.
    {
        let mut painter = SkiaPainter::with_transform(ctx.pixmap, ctx.transform);
        paint_cobblestone(&op, seed, &mut painter);
        paint_brick(&op, seed, &mut painter);
        paint_flagstone(&op, seed, &mut painter);
        paint_opus_romano(&op, seed, &mut painter);
    }

    // Legacy `paint_fragments` sub-handlers. These will port to
    // the Painter trait one at a time in 2.13e–g; until each ships,
    // they own the `&mut Pixmap` via `RasterCtx` directly.
    draw_field_stone(&op, seed, ctx);
    draw_cart_tracks(&op, seed, ctx);
    draw_ore_deposit(&op, seed, ctx);
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

fn draw_field_stone(op: &DecoratorOp<'_>, seed: u64, ctx: &mut RasterCtx<'_>) {
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
        let frags = primitives::field_stone::draw_field_stone(&tiles, seed);
        paint_fragments(&frags, 1.0, None, ctx);
    }
}

fn draw_cart_tracks(op: &DecoratorOp<'_>, seed: u64, ctx: &mut RasterCtx<'_>) {
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
        let frags = primitives::cart_tracks::draw_cart_tracks(&tiles, seed);
        paint_fragments(&frags, 1.0, None, ctx);
    }
}

fn draw_ore_deposit(op: &DecoratorOp<'_>, seed: u64, ctx: &mut RasterCtx<'_>) {
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
        let frags = primitives::ore_deposit::draw_ore_deposit(&tiles, seed);
        paint_fragments(&frags, 1.0, None, ctx);
    }
}

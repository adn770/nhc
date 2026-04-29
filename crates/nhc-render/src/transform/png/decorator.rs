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

use crate::ir::{DecoratorOp, FloorIR, OpEntry};
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

    draw_cobblestone(&op, seed, ctx);
    draw_brick(&op, seed, ctx);
    draw_flagstone(&op, seed, ctx);
    draw_opus_romano(&op, seed, ctx);
    draw_field_stone(&op, seed, ctx);
    draw_cart_tracks(&op, seed, ctx);
    draw_ore_deposit(&op, seed, ctx);
}

fn draw_cobblestone(op: &DecoratorOp<'_>, seed: u64, ctx: &mut RasterCtx<'_>) {
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
        let frags = primitives::cobblestone::draw_cobblestone(&tiles, seed);
        paint_fragments(&frags, 1.0, None, ctx);
    }
}

fn draw_brick(op: &DecoratorOp<'_>, seed: u64, ctx: &mut RasterCtx<'_>) {
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
        let frags = primitives::brick::draw_brick(&tiles, seed);
        paint_fragments(&frags, 1.0, None, ctx);
    }
}

fn draw_flagstone(op: &DecoratorOp<'_>, seed: u64, ctx: &mut RasterCtx<'_>) {
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
        let frags = primitives::flagstone::draw_flagstone(&tiles, seed);
        paint_fragments(&frags, 1.0, None, ctx);
    }
}

fn draw_opus_romano(op: &DecoratorOp<'_>, seed: u64, ctx: &mut RasterCtx<'_>) {
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
        let frags = primitives::opus_romano::draw_opus_romano(&tiles, seed);
        paint_fragments(&frags, 1.0, None, ctx);
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

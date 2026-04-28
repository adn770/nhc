//! Procedural primitives — one module per IR op.
//!
//! Each submodule (`shadow`, `hatch`, `walls`, `floor_grid`, …)
//! reproduces the SVG output of its sibling helper in
//! `nhc/rendering/_*.py` byte-for-byte. The contract is:
//!
//! - Parameters are passed via the corresponding FlatBuffers op
//!   table (deserialised by the FFI layer; primitives never see
//!   raw bytes).
//! - RNG is seeded from `op.seed`, derived from `floor.base_seed`
//!   per the offsets in `design/ir_primitives.md` (Phase 0.8).
//! - Output is either an SVG path-fragment list (Phase 1 parity
//!   path) or a typed-array opcode stream (Phase 5+ PNG / Canvas).
//!
//! **`floor_grid` is the Phase 3 canary**, then heaviest-first
//! (`hatch`, `floor_detail`, …) per
//! `plans/nhc_ir_migration_plan.md` Phase 4.

pub mod brick;
pub mod cobblestone;
pub mod flagstone;
pub mod floor_detail;
pub mod floor_grid;
pub mod hatch;
pub mod shadow;
pub mod stairs;
pub mod terrain_tints;
pub mod thematic_detail;
pub mod walls_and_floors;

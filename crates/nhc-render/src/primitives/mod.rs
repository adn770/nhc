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
//! **Empty until Phase 3.** Submodules drop in primitive-by-
//! primitive per the order in `plans/nhc_ir_migration_plan.md`
//! Phase 4. `floor_grid` is the canary in Phase 3, then heaviest-
//! first (`hatch`, `floor_detail`, …).

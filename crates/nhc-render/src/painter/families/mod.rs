//! Per-family painter modules — Phase 1.2 of
//! `plans/nhc_pure_ir_v5_migration_plan.md`.
//!
//! Each family ships as one module under this directory. The
//! module-level `paint(painter, region_path, material)` function
//! is the entry point invoked by the `material::paint_material`
//! dispatcher.
//!
//! Phase 1.2 lands stubs: each family fills the region with a
//! sentinel placeholder colour so the dispatch contract compiles
//! and the test surface is in place. Phase 2 commits replace each
//! family's stub with the real per-style / per-tone palette and
//! layout algorithm.

pub mod cave;
pub mod earth;
pub mod liquid;
pub mod plain;
pub mod special;
pub mod stone;
pub mod wood;

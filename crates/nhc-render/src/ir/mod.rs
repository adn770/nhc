//! FlatBuffers-generated bindings for the floor IR.
//!
//! `floor_ir_generated.rs` is produced by `make ir-bindings` from
//! `nhc/rendering/ir/floor_ir.fbs`. The generated code declares a
//! nested `pub mod nhc { pub mod rendering { pub mod ir { pub mod
//! _fb { ... } } } }` chain to mirror the schema namespace; this
//! module re-exports the leaf path so call sites can write
//! `use crate::ir::FloorIR;` instead of carrying the full namespace
//! prefix everywhere.

#![allow(unused_imports, dead_code, clippy::all)]

mod floor_ir_generated;

pub use floor_ir_generated::nhc::rendering::ir::_fb::*;

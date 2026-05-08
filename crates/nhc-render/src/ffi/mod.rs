//! FFI shims — one submodule per ABI.
//!
//! Today only the PyO3 shim lives here. The wasm-bindgen
//! exports relocated to the standalone ``nhc-render-wasm``
//! workspace member at Phase 5.1, since wasm-pack works against
//! a clean cdylib-only crate and the two FFI surfaces export
//! overlapping symbol names with different calling conventions.
//!
//! The shim is thin: it deserialises FlatBuffers IR, calls into
//! ``crate::primitives`` / ``crate::transform``, and boxes the
//! result in the target ABI's container type.
//!
//! Cross-cutting helpers (e.g. polygon → path-fragment helpers)
//! belong in ``primitives/``, not here. The FFI layer should
//! stay mechanical so the determinism contract lives in one
//! place.

#[cfg(feature = "pyo3")]
pub mod pyo3;

//! FFI shims — one submodule per ABI.
//!
//! The two surfaces are mutually exclusive at the feature level:
//! a single build of the crate either targets PyO3 (server-side
//! Python wheel, default) or wasm-bindgen (browser bundle), never
//! both. Both shims are thin: they deserialise FlatBuffers IR,
//! call into `crate::primitives` / `crate::transform`, and box
//! the result in the target ABI's container type.
//!
//! Cross-cutting helpers (e.g. polygon → path-fragment helpers)
//! belong in `primitives/`, not here. The FFI layer should stay
//! mechanical so the determinism contract lives in one place.

#[cfg(feature = "pyo3")]
pub mod pyo3;

#[cfg(all(feature = "wasm", not(feature = "pyo3")))]
pub mod wasm;

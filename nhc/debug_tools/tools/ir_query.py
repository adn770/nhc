"""IR query tools for inspecting FloorIR FlatBuffers.

Phase 2.4 of plans/nhc_ir_migration_plan.md: lift the IR onto the
MCP debug surface so a Claude Code session can introspect the IR
the renderer produced without a round-trip through the SVG. Each
tool reads a ``floor_ir_*.nir`` FlatBuffer (defaulting to the most
recent under ``debug/exports/``) and answers structural queries
via the canonical JSON dump from :mod:`nhc.rendering.ir.dump`.

Tools:

- :class:`GetIRBufferTool` — buffer metadata + optional canonical dump
- :class:`GetIRRegionTool` — list regions, or fetch one by id
- :class:`GetIROpsTool` — op-vector summary, or filter by kind
- :class:`GetIRDiffTool` — structural diff between two .nir files
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nhc.debug_tools.base import BaseTool


def _latest_nir(exports_dir: Path) -> Path | None:
    if not exports_dir.exists():
        return None
    matches = sorted(
        exports_dir.glob("floor_ir_*.nir"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def _resolve_nir(
    exports_dir: Path, path: str | None,
) -> tuple[Path | None, dict | None]:
    """Return (resolved_path, error_dict). One is None."""
    if path:
        p = Path(path)
        if not p.exists():
            return None, {"error": f"file not found: {path}"}
        return p, None
    p = _latest_nir(exports_dir)
    if p is None:
        return None, {
            "error": (
                "No floor_ir_*.nir export found in "
                f"{exports_dir}. Pass path= explicitly or run the "
                "/api/game/<sid>/export/floor_ir route to populate."
            ),
        }
    return p, None


def _load_dump(buf: bytes) -> dict[str, Any]:
    from nhc.rendering.ir.dump import dump
    return json.loads(dump(buf))


class GetIRBufferTool(BaseTool):
    """Buffer metadata for a FloorIR FlatBuffer."""

    name = "get_ir_buffer"
    description = (
        "Inspect a FloorIR FlatBuffer: schema version, region / op "
        "counts, file identifier, optional canonical JSON dump for "
        "offline analysis."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Path to a .nir file. Defaults to the most "
                    "recent debug/exports/floor_ir_*.nir."
                ),
            },
            "include_dump": {
                "type": "boolean",
                "description": (
                    "Include the full canonicalised JSON dump in "
                    "the response. Off by default; the dump can "
                    "be large."
                ),
            },
        },
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        path, err = _resolve_nir(
            self.exports_dir, kwargs.get("path"),
        )
        if err is not None:
            return err
        buf = path.read_bytes()
        try:
            d = _load_dump(buf)
        except ValueError as exc:
            return {"error": f"not a FloorIR buffer: {exc}"}
        out: dict[str, Any] = {
            "path": str(path),
            "size_bytes": len(buf),
            "file_identifier": (
                buf[4:8].decode("ascii", errors="replace")
                if len(buf) >= 8 else ""
            ),
            "major": d["major"],
            "minor": d["minor"],
            "region_count": len(d.get("regions") or []),
            "op_count": len(d.get("ops") or []),
        }
        if kwargs.get("include_dump"):
            from nhc.rendering.ir.dump import dump
            out["dump"] = dump(buf)
        return out


class GetIRRegionTool(BaseTool):
    """List regions, or fetch one by id."""

    name = "get_ir_region"
    description = (
        "Without region_id, list all regions in the IR (id + kind). "
        "With region_id, return the matching region's full data "
        "(kind, shape_tag, polygon)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Path to a .nir file. Defaults to the most "
                    "recent debug/exports/floor_ir_*.nir."
                ),
            },
            "region_id": {
                "type": "string",
                "description": (
                    "Region id to fetch (e.g. 'dungeon', "
                    "'room_1', 'cave_0'). Omit to list all."
                ),
            },
        },
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        path, err = _resolve_nir(
            self.exports_dir, kwargs.get("path"),
        )
        if err is not None:
            return err
        d = _load_dump(path.read_bytes())
        regions = d.get("regions") or []
        region_id = kwargs.get("region_id")
        if region_id is None:
            return {
                "path": str(path),
                "regions": [
                    {
                        "id": r["id"],
                        "kind": r["kind"],
                        "shape_tag": r.get("shapeTag", ""),
                    }
                    for r in regions
                ],
            }
        for r in regions:
            if r["id"] == region_id:
                return {"path": str(path), "region": r}
        return {
            "error": f"region_id {region_id!r} not found",
            "available": [r["id"] for r in regions],
        }


class GetIROpsTool(BaseTool):
    """Op-vector summary, or filter by kind."""

    name = "get_ir_ops"
    description = (
        "Without kind, return per-op-kind counts (e.g. ShadowOp: "
        "12, HatchOp: 8). With kind, return all ops of that kind "
        "with full op data."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Path to a .nir file. Defaults to the most "
                    "recent debug/exports/floor_ir_*.nir."
                ),
            },
            "kind": {
                "type": "string",
                "description": (
                    "Op type name to filter by (e.g. 'ShadowOp', "
                    "'HatchOp', 'StairsOp'). Omit for summary."
                ),
            },
        },
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        path, err = _resolve_nir(
            self.exports_dir, kwargs.get("path"),
        )
        if err is not None:
            return err
        d = _load_dump(path.read_bytes())
        ops = d.get("ops") or []
        kind = kwargs.get("kind")
        if kind is None:
            summary: dict[str, int] = {}
            for entry in ops:
                ot = entry.get("opType", "?")
                summary[ot] = summary.get(ot, 0) + 1
            return {
                "path": str(path),
                "total": len(ops),
                "summary": summary,
            }
        matching = [o for o in ops if o.get("opType") == kind]
        return {
            "path": str(path),
            "kind": kind,
            "count": len(matching),
            "ops": matching,
        }


class GetIRDiffTool(BaseTool):
    """Structural diff between two FloorIR FlatBuffers."""

    name = "get_ir_diff"
    description = (
        "Compare two .nir buffers: which region ids appear or "
        "disappear, and the net change in ops per kind. Useful "
        "for catching regressions in IR emission across commits "
        "or fixtures."
    )
    parameters = {
        "type": "object",
        "properties": {
            "before": {
                "type": "string",
                "description": "Path to the baseline .nir.",
            },
            "after": {
                "type": "string",
                "description": "Path to the candidate .nir.",
            },
        },
        "required": ["before", "after"],
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        before, after = kwargs["before"], kwargs["after"]
        for label, p in (("before", before), ("after", after)):
            if not Path(p).exists():
                return {
                    "error": f"{label} file not found: {p}",
                }
        d1 = _load_dump(Path(before).read_bytes())
        d2 = _load_dump(Path(after).read_bytes())
        ids1 = {r["id"] for r in (d1.get("regions") or [])}
        ids2 = {r["id"] for r in (d2.get("regions") or [])}
        op_counts_1: dict[str, int] = {}
        for entry in (d1.get("ops") or []):
            ot = entry.get("opType", "?")
            op_counts_1[ot] = op_counts_1.get(ot, 0) + 1
        op_counts_2: dict[str, int] = {}
        for entry in (d2.get("ops") or []):
            ot = entry.get("opType", "?")
            op_counts_2[ot] = op_counts_2.get(ot, 0) + 1
        # Per-kind net changes (positive = added in `after`).
        kinds = sorted(set(op_counts_1) | set(op_counts_2))
        per_kind = {
            k: op_counts_2.get(k, 0) - op_counts_1.get(k, 0)
            for k in kinds
            if op_counts_1.get(k, 0) != op_counts_2.get(k, 0)
        }
        added = max(0, sum(op_counts_2.values()) - sum(op_counts_1.values()))
        removed = max(0, sum(op_counts_1.values()) - sum(op_counts_2.values()))
        return {
            "before": before,
            "after": after,
            "regions_added": sorted(ids2 - ids1),
            "regions_removed": sorted(ids1 - ids2),
            "ops_added": added,
            "ops_removed": removed,
            "ops_net_per_kind": per_kind,
        }

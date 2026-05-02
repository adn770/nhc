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
- :class:`GetWallCoverageTool` — legacy + new-op wall summary
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nhc.debug_tools.base import BaseTool


# ---------------------------------------------------------------------------
# WallStyle / OutlineKind reverse maps (stable enums — hardcoded for clarity)
# ---------------------------------------------------------------------------

_WALL_STYLE: dict[int, str] = {
    0: "DungeonInk",
    1: "CaveInk",
    2: "MasonryBrick",
    3: "MasonryStone",
    4: "PartitionStone",
    5: "PartitionBrick",
    6: "PartitionWood",
    7: "Palisade",
    8: "FortificationMerlon",
}

_OUTLINE_KIND: dict[int, str] = {
    0: "Polygon",
    1: "Circle",
    2: "Pill",
}


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
    exports_dir: Path,
    path: str | None,
    fixture: str | None = None,
) -> tuple[Path | None, dict | None]:
    """Return (resolved_path, error_dict). One is None.

    Resolution order:
    1. fixture=<name>: tests/fixtures/floor_ir/<name>/floor.nir
    2. path=<path>: explicit file path
    3. Default: latest debug/exports/floor_ir_*.nir
    """
    if fixture:
        # Fixtures live under project root; use Path() so the MCP
        # server's CWD (project root) resolves correctly.
        p = Path("tests/fixtures/floor_ir") / fixture / "floor.nir"
        if not p.exists():
            available: list[str] = []
            root = Path("tests/fixtures/floor_ir")
            if root.exists():
                available = sorted(
                    d.name for d in root.iterdir() if d.is_dir()
                )
            return None, {
                "error": f"fixture not found: {fixture!r}",
                "available": available,
            }
        return p, None
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
            "fixture": {
                "type": "string",
                "description": (
                    "Fixture name under tests/fixtures/floor_ir/. "
                    "Auto-resolves to <name>/floor.nir. "
                    "Overrides path= when given."
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
            self.exports_dir,
            kwargs.get("path"),
            kwargs.get("fixture"),
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
            "fixture": {
                "type": "string",
                "description": (
                    "Fixture name under tests/fixtures/floor_ir/. "
                    "Auto-resolves to <name>/floor.nir. "
                    "Overrides path= when given."
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
            self.exports_dir,
            kwargs.get("path"),
            kwargs.get("fixture"),
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
            "fixture": {
                "type": "string",
                "description": (
                    "Fixture name under tests/fixtures/floor_ir/. "
                    "Auto-resolves to <name>/floor.nir. "
                    "Overrides path= when given."
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
            self.exports_dir,
            kwargs.get("path"),
            kwargs.get("fixture"),
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
            "fixture_before": {
                "type": "string",
                "description": (
                    "Fixture name for the baseline. "
                    "Auto-resolves to tests/fixtures/floor_ir/"
                    "<name>/floor.nir. Overrides before= when given."
                ),
            },
            "fixture_after": {
                "type": "string",
                "description": (
                    "Fixture name for the candidate. "
                    "Auto-resolves to tests/fixtures/floor_ir/"
                    "<name>/floor.nir. Overrides after= when given."
                ),
            },
        },
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        # Resolve before path
        before_path, err = _resolve_nir(
            self.exports_dir,
            kwargs.get("before"),
            kwargs.get("fixture_before"),
        )
        if err is not None:
            return {"error": f"before: {err['error']}"}

        # Resolve after path
        after_path, err = _resolve_nir(
            self.exports_dir,
            kwargs.get("after"),
            kwargs.get("fixture_after"),
        )
        if err is not None:
            return {"error": f"after: {err['error']}"}

        d1 = _load_dump(before_path.read_bytes())
        d2 = _load_dump(after_path.read_bytes())
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
            "before": str(before_path),
            "after": str(after_path),
            "regions_added": sorted(ids2 - ids1),
            "regions_removed": sorted(ids1 - ids2),
            "ops_added": added,
            "ops_removed": removed,
            "ops_net_per_kind": per_kind,
        }


class GetWallCoverageTool(BaseTool):
    """Wall coverage summary for a FloorIR FlatBuffer."""

    name = "get_wall_coverage"
    description = (
        "Report legacy wall data (counts from WallsAndFloorsOp) "
        "and new-op summary (ExteriorWallOp / InteriorWallOp / "
        "CorridorWallOp) for a .nir buffer. Useful for diagnosing "
        "migration progress during 1.17 / 1.18 / 1.19 where wall "
        "data flows through both paths."
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
            "fixture": {
                "type": "string",
                "description": (
                    "Fixture name under tests/fixtures/floor_ir/. "
                    "Auto-resolves to <name>/floor.nir. "
                    "Overrides path= when given."
                ),
            },
        },
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        path, err = _resolve_nir(
            self.exports_dir,
            kwargs.get("path"),
            kwargs.get("fixture"),
        )
        if err is not None:
            return err
        d = _load_dump(path.read_bytes())
        ops = d.get("ops") or []

        # Legacy fields (from WallsAndFloorsOp)
        wall_segments = 0
        smooth_walls = 0
        wall_ext_d = 0
        cave_region = False

        # New-op accumulators
        exterior_walls: list[dict[str, Any]] = []
        interior_walls: list[dict[str, Any]] = []
        corridor_wall_op: dict[str, Any] | None = None

        for entry in ops:
            op_type = entry.get("opType", "")
            op = entry.get("op", {})

            if op_type == "WallsAndFloorsOp":
                wall_segments = len(op.get("wallSegments") or [])
                smooth_walls = len(op.get("smoothRoomRegions") or [])
                wall_ext_d = len(op.get("wallExtensionsDChars") or [])
                # Phase 1.19: caveRegion is the empty string in fresh
                # IR; treat it as "absent" so the report reflects the
                # consumer-facing reality (the new pipeline reads
                # CaveFloor FloorOp.outline.vertices instead).
                cave_region = bool(op.get("caveRegion"))

            elif op_type == "ExteriorWallOp":
                outline = op.get("outline") or {}
                style_int = op.get("style", 0)
                dk = outline.get("descriptorKind", 0)
                exterior_walls.append({
                    "style": _WALL_STYLE.get(style_int, str(style_int)),
                    "outline_kind": _OUTLINE_KIND.get(dk, str(dk)),
                    "vertices_count": len(outline.get("vertices") or []),
                    "cuts_count": len(outline.get("cuts") or []),
                })

            elif op_type == "InteriorWallOp":
                outline = op.get("outline") or {}
                style_int = op.get("style", 0)
                dk = outline.get("descriptorKind", 0)
                interior_walls.append({
                    "style": _WALL_STYLE.get(style_int, str(style_int)),
                    "outline_kind": _OUTLINE_KIND.get(dk, str(dk)),
                    "vertices_count": len(outline.get("vertices") or []),
                    "cuts_count": len(outline.get("cuts") or []),
                    "closed": outline.get("closed", False),
                })

            elif op_type == "CorridorWallOp":
                style_int = op.get("style", 0)
                corridor_wall_op = {
                    "tiles_count": len(op.get("tiles") or []),
                    "style": _WALL_STYLE.get(style_int, str(style_int)),
                }

        # by_style: count ExteriorWallOps per style
        by_style: dict[str, int] = {}
        for w in exterior_walls:
            s = w["style"]
            by_style[s] = by_style.get(s, 0) + 1

        return {
            "path": str(path),
            "legacy": {
                "wall_segments_count": wall_segments,
                "smooth_walls_count": smooth_walls,
                "wall_extensions_d_chars": wall_ext_d,
                "cave_region_present": cave_region,
            },
            "new": {
                "exterior_walls": exterior_walls,
                "interior_walls": interior_walls,
                "corridor_wall_op": corridor_wall_op,
            },
            "by_style": by_style,
        }

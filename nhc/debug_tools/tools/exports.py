"""Tools for listing and reading exported debug files."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from nhc.debug_tools.base import BaseTool


class ListExportsTool(BaseTool):
    name = "list_exports"
    description = (
        "List exported debug files in debug/exports/. "
        "Optionally filter by type (game_state, layer_state, map)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "type_filter": {
                "type": "string",
                "description": (
                    "Filter by export type: game_state, "
                    "layer_state, or map"
                ),
            },
        },
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        type_filter = kwargs.get("type_filter")
        if not self.exports_dir.exists():
            return {"exports": [], "count": 0}
        files = []
        for p in sorted(self.exports_dir.iterdir(),
                        key=lambda f: f.stat().st_mtime,
                        reverse=True):
            if not p.is_file():
                continue
            name = p.name
            if type_filter and not name.startswith(type_filter):
                continue
            ext = p.suffix
            ftype = name.split("_")[0]
            if name.startswith("game_state"):
                ftype = "game_state"
            elif name.startswith("layer_state"):
                ftype = "layer_state"
            elif name.startswith("map"):
                ftype = "map"
            st = p.stat()
            files.append({
                "filename": name,
                "type": ftype,
                "size_bytes": st.st_size,
                "modified": datetime.fromtimestamp(
                    st.st_mtime).isoformat(),
            })
        return {"exports": files, "count": len(files)}


class ReadExportTool(BaseTool):
    name = "read_export"
    description = (
        "Read and parse an exported debug file. JSON files are "
        "parsed, SVG files returned as text."
    )
    parameters = {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Filename in debug/exports/",
            },
        },
        "required": ["filename"],
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        filename = kwargs["filename"]
        path = self.exports_dir / filename
        if not path.exists():
            return {"error": f"File not found: {filename}"}
        text = path.read_text()
        if path.suffix == ".json":
            return {"filename": filename, "data": json.loads(text)}
        return {"filename": filename, "content": text}

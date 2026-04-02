"""Base class for nhc debug tools.

Adapted from mdt/vmdbg BaseTool pattern — simplified for
export-file-based diagnostics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class BaseTool:
    """Base class for all nhc debug tools."""

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
    }

    def __init__(self) -> None:
        self.exports_dir = Path("debug/exports")

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError

    def _latest_export(self, prefix: str) -> Path | None:
        """Find the most recent export file matching prefix."""
        if not self.exports_dir.exists():
            return None
        matches = sorted(
            self.exports_dir.glob(f"{prefix}_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return matches[0] if matches else None

    def _read_json_export(
        self, prefix: str, filename: str | None = None,
    ) -> dict[str, Any]:
        """Read and parse a JSON export file.

        If filename is given, reads that specific file.
        Otherwise reads the most recent file matching prefix.
        """
        if filename:
            path = self.exports_dir / filename
        else:
            path = self._latest_export(prefix)
        if not path or not path.exists():
            return {"error": f"No {prefix} export found"}
        return json.loads(path.read_text())

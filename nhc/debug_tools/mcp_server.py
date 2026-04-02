#!/usr/bin/env python3
"""NHC debug MCP server — game state diagnostic tools.

Reads exported game state files from debug/exports/ and
provides query tools for diagnosing rendering and gameplay
issues.

Usage:
    .venv/bin/python -m nhc.debug_tools.mcp_server
"""

import logging
import sys
import time as _time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context
from mcp.server.fastmcp.tools.base import Tool as MCPTool
from mcp.server.fastmcp.utilities.func_metadata import func_metadata

# Setup file logging
log_dir = Path(__file__).parent.parent.parent / "debug" / "mcp_logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / (
    f"nhc_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
)

_root_logger = logging.getLogger("nhc.debug_tools")
_root_logger.setLevel(logging.DEBUG)

_fh = logging.FileHandler(log_file, encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
))
_root_logger.addHandler(_fh)

_sh = logging.StreamHandler(sys.stderr)
_sh.setLevel(logging.WARNING)
_root_logger.addHandler(_sh)

logger = logging.getLogger(__name__)
logger.info("Log file: %s", log_file)

# -------------------------------------------------------------------
# FastMCP instance
# -------------------------------------------------------------------

mcp = FastMCP("nhc-debug")

# -------------------------------------------------------------------
# Type map for dynamic handler generation
# -------------------------------------------------------------------

_TYPE_MAP: Dict[str, str] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
}

# -------------------------------------------------------------------
# Tool execution
# -------------------------------------------------------------------


async def _execute_tool(
    tool_class: type, kwargs: dict, ctx: Any,
) -> dict:
    """Instantiate and execute a tool."""
    tool_name = tool_class.name
    t0 = _time.perf_counter()
    logger.info("Executing %s(%s)", tool_name, kwargs)

    try:
        tool = tool_class()
        result = await tool.execute(**kwargs)
        elapsed = _time.perf_counter() - t0
        logger.info("Tool %s completed in %.2fs", tool_name, elapsed)
        return result
    except Exception as e:
        elapsed = _time.perf_counter() - t0
        logger.error(
            "Tool %s failed after %.2fs: %s: %s",
            tool_name, elapsed, type(e).__name__, e,
            exc_info=True,
        )
        raise


def _build_handler(tool_class: type) -> Callable:
    """Build MCP handler with explicit parameter signature."""
    tool_instance = tool_class()
    props = tool_instance.parameters.get("properties", {})
    required = set(tool_instance.parameters.get("required", []))

    req_parts: list[str] = []
    opt_parts: list[str] = []
    names: list[str] = []

    for pname, pschema in props.items():
        py_type = _TYPE_MAP.get(
            pschema.get("type", "string"), "str"
        )
        names.append(pname)
        if pname in required:
            req_parts.append(f"{pname}: {py_type}")
        else:
            opt_parts.append(f"{pname}: {py_type} | None = None")

    opt_parts.append("ctx: _Ctx = None")
    sig = ", ".join(req_parts + opt_parts)
    kw_items = ", ".join(f'"{n}": {n}' for n in names)

    code = (
        f"async def _handler({sig}) -> dict:\n"
        f"    kw = {{{kw_items}}}\n"
        f"    kw = {{k: v for k, v in kw.items() "
        f"if v is not None}}\n"
        f"    return await _exec(_tool_class, kw, ctx)\n"
    )

    ns: Dict[str, Any] = {
        "_exec": _execute_tool,
        "_tool_class": tool_class,
        "_Ctx": Context,
    }
    exec(code, ns)  # noqa: S102
    return ns["_handler"]


def _register_tools() -> None:
    """Register all tools from tool modules."""
    logger.info("Starting tool registration...")

    from nhc.debug_tools.tools import ALL_TOOL_CLASSES

    registered = 0
    for tool_class in ALL_TOOL_CLASSES:
        try:
            tool_instance = tool_class()
            handler = _build_handler(tool_class)
            meta = func_metadata(handler)

            mcp_tool = MCPTool(
                fn=handler,
                name=tool_instance.name,
                description=tool_instance.description,
                parameters=tool_instance.parameters,
                fn_metadata=meta,
                is_async=True,
                context_kwarg="ctx",
            )

            mcp._tool_manager._tools[
                tool_instance.name
            ] = mcp_tool
            registered += 1
            logger.debug("Registered: %s", tool_instance.name)

        except Exception as e:
            logger.error(
                "Failed to register %s: %s",
                tool_class.__name__, e,
                exc_info=True,
            )

    logger.info(
        "Registered %d/%d nhc-debug tools",
        registered, len(ALL_TOOL_CLASSES),
    )
    tool_names = list(mcp._tool_manager._tools.keys())
    logger.info("Available tools: %s", ", ".join(tool_names))


# -------------------------------------------------------------------
# Server Entry Point
# -------------------------------------------------------------------

logger.info("Registering tools at module level...")
_register_tools()
logger.info("Tool registration complete — server ready")

if __name__ == "__main__":
    logger.info("=== Starting mcp.run() ===")
    mcp.run()
    logger.info("mcp.run() returned (server shutdown)")

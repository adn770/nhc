"""Hexcrawl world generator dispatch.

The active generator is ``continental``, a nine-stage pipeline
described in ``design/hexcrawl_generator.md``. The implementation
lives in :mod:`nhc.hexcrawl._generator`; this module re-exports
:func:`generate_continental_world` as the public entry point.
"""

from nhc.hexcrawl._generator import (  # noqa: F401
    GeneratorRetryError,
    generate_continental_world,
)

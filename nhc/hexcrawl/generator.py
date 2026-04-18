"""Hexcrawl world generator dispatch.

The active generator is ``continental_v2``, a nine-stage pipeline
described in ``design/hexcrawl_generator.md``. The implementation
lives in :mod:`nhc.hexcrawl._gen_v2`; this module re-exports
:func:`generate_continental_world` as the public entry point.
"""

from nhc.hexcrawl._gen_v2 import (  # noqa: F401
    GeneratorRetryError,
    generate_continental_world,
)

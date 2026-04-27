"""Build / deployment metadata for the welcome-page badge.

Surfaces the running container's git SHA + build timestamp on the
welcome page so the deployer can verify at-a-glance which image is
live. Source of truth: two env vars set by ``deploy/update.sh`` at
docker-build time:

- ``NHC_GIT_SHA``     — short SHA of the deployed commit
- ``NHC_BUILD_TIME``  — ISO 8601 UTC timestamp of the docker build

When unset (local ``./server``), each slot falls back to ``"dev"``
independently — a missing one shouldn't produce a misleading
fallback for the other.
"""

from __future__ import annotations

import os


def get_build_info() -> dict[str, str]:
    """Return ``{"sha": <git sha>, "time": <iso timestamp>}``.

    Reads from env vars at call time so test monkeypatching works
    without app-factory rebuilds.
    """
    return {
        "sha": os.environ.get("NHC_GIT_SHA", "dev"),
        "time": os.environ.get("NHC_BUILD_TIME", "dev"),
    }

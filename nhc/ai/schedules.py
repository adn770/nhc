"""Daily-routine builders for town citizens.

A :class:`DailyRoutine` maps each :class:`TimeOfDay` segment to a
:class:`RoutineAnchor` the citizen drifts toward. These builders
encode the per-family day shape (see ``design/town_life.md``) so the
town spawner and tests construct routines the same way. Anchors are
concrete tiles resolved at spawn time from generated features.
"""

from __future__ import annotations

from nhc.entities.components import DailyRoutine, RoutineAnchor
from nhc.hexcrawl.model import TimeOfDay


def build_worker_routine(
    workplace: tuple[int, int],
    home: tuple[int, int] | None = None,
    *,
    work_weight: float = 0.85,
) -> DailyRoutine:
    """Routine for working folk: at the workplace through the day,
    home (and gone) at night.

    The citizen anchors near ``workplace`` across morning, midday and
    evening — pulling weakest in the evening as the day winds down.
    At ``NIGHT`` it routes to ``home`` and despawns, so the streets
    empty after dark. With no ``home`` the night segment is left
    unscheduled and the citizen falls back to free wandering.
    """
    wx, wy = workplace
    anchors: dict[TimeOfDay, RoutineAnchor] = {
        TimeOfDay.MORNING: RoutineAnchor(wx, wy, work_weight),
        TimeOfDay.MIDDAY: RoutineAnchor(wx, wy, work_weight),
        TimeOfDay.EVENING: RoutineAnchor(wx, wy, work_weight * 0.8),
    }
    if home is not None:
        hx, hy = home
        anchors[TimeOfDay.NIGHT] = RoutineAnchor(hx, hy, 1.0, despawn=True)
    return DailyRoutine(anchors=anchors)

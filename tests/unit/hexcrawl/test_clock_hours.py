"""Tests for hour-precision clock on HexWorld.

Milestone M2: advance_clock_hours(), hour/minute fields,
segment-to-hour delegation.
"""

from __future__ import annotations

import pytest

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import HexWorld, TimeOfDay


def _make_world() -> HexWorld:
    w = HexWorld(pack_id="test", seed=1, width=4, height=4)
    return w


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


def test_hour_defaults_to_six() -> None:
    w = _make_world()
    assert w.hour == 6


def test_minute_defaults_to_zero() -> None:
    w = _make_world()
    assert w.minute == 0


def test_initial_time_is_morning() -> None:
    w = _make_world()
    assert w.time is TimeOfDay.MORNING


# ---------------------------------------------------------------------------
# advance_clock_hours — within a segment
# ---------------------------------------------------------------------------


def test_advance_one_hour_from_morning() -> None:
    w = _make_world()
    w.advance_clock_hours(1.0)
    assert w.hour == 7
    assert w.minute == 0
    assert w.time is TimeOfDay.MORNING
    assert w.day == 1


def test_advance_fractional_hours() -> None:
    w = _make_world()
    w.advance_clock_hours(1.5)
    assert w.hour == 7
    assert w.minute == 30
    assert w.time is TimeOfDay.MORNING


def test_advance_30_minutes() -> None:
    w = _make_world()
    w.advance_clock_hours(0.5)
    assert w.hour == 6
    assert w.minute == 30


# ---------------------------------------------------------------------------
# advance_clock_hours — crossing segment boundaries
# ---------------------------------------------------------------------------


def test_advance_crosses_morning_to_midday() -> None:
    w = _make_world()  # 6:00 MORNING
    w.advance_clock_hours(6.0)
    assert w.hour == 12
    assert w.minute == 0
    assert w.time is TimeOfDay.MIDDAY
    assert w.day == 1


def test_advance_crosses_to_evening() -> None:
    w = _make_world()
    w.advance_clock_hours(12.0)
    assert w.hour == 18
    assert w.minute == 0
    assert w.time is TimeOfDay.EVENING
    assert w.day == 1


def test_advance_crosses_to_night() -> None:
    w = _make_world()
    w.advance_clock_hours(18.0)
    assert w.hour == 0
    assert w.minute == 0
    assert w.time is TimeOfDay.NIGHT
    assert w.day == 2


# ---------------------------------------------------------------------------
# advance_clock_hours — crossing day boundary
# ---------------------------------------------------------------------------


def test_advance_18_and_a_half_hours() -> None:
    w = _make_world()  # day 1, 6:00
    w.advance_clock_hours(18.5)
    assert w.hour == 0
    assert w.minute == 30
    assert w.time is TimeOfDay.NIGHT
    assert w.day == 2


def test_advance_full_day() -> None:
    w = _make_world()
    w.advance_clock_hours(24.0)
    assert w.hour == 6
    assert w.minute == 0
    assert w.time is TimeOfDay.MORNING
    assert w.day == 2


def test_advance_multiple_days() -> None:
    w = _make_world()  # day 1, 6:00
    w.advance_clock_hours(48.0 + 6.0)  # 2 days + 6 hours
    assert w.hour == 12
    assert w.minute == 0
    assert w.time is TimeOfDay.MIDDAY
    assert w.day == 3


# ---------------------------------------------------------------------------
# advance_clock_hours — accumulation
# ---------------------------------------------------------------------------


def test_multiple_small_advances_accumulate() -> None:
    w = _make_world()
    for _ in range(10):
        w.advance_clock_hours(0.5)  # 10 × 30 min = 5 hours
    assert w.hour == 11
    assert w.minute == 0
    assert w.time is TimeOfDay.MORNING


def test_ten_minute_turns_accumulate() -> None:
    """Six 10-minute advances = 1 hour."""
    w = _make_world()  # 6:00
    for _ in range(6):
        w.advance_clock_hours(1 / 6)
    assert w.hour == 7
    assert w.minute == 0


# ---------------------------------------------------------------------------
# Segment-based advance_clock still works
# ---------------------------------------------------------------------------


def test_advance_clock_one_segment_equals_six_hours() -> None:
    w = _make_world()  # 6:00 MORNING
    w.advance_clock(1)
    assert w.hour == 12
    assert w.minute == 0
    assert w.time is TimeOfDay.MIDDAY
    assert w.day == 1


def test_advance_clock_four_segments_rolls_day() -> None:
    w = _make_world()
    w.advance_clock(4)
    assert w.hour == 6
    assert w.minute == 0
    assert w.time is TimeOfDay.MORNING
    assert w.day == 2


def test_advance_clock_ten_segments() -> None:
    w = _make_world()
    w.advance_clock(10)  # 2 days + 2 segments = 60 hours
    assert w.hour == 18
    assert w.minute == 0
    assert w.time is TimeOfDay.EVENING
    assert w.day == 3


def test_advance_clock_rejects_negative() -> None:
    w = _make_world()
    with pytest.raises(ValueError):
        w.advance_clock(-1)


# ---------------------------------------------------------------------------
# Segment derivation from hours
# ---------------------------------------------------------------------------


def test_segment_mapping_morning() -> None:
    """Hours 6-11 → MORNING."""
    w = _make_world()
    for h in range(6, 12):
        w.hour = h
        w._sync_time_from_hour()
        assert w.time is TimeOfDay.MORNING, f"hour {h}"


def test_segment_mapping_midday() -> None:
    """Hours 12-17 → MIDDAY."""
    w = _make_world()
    for h in range(12, 18):
        w.hour = h
        w._sync_time_from_hour()
        assert w.time is TimeOfDay.MIDDAY, f"hour {h}"


def test_segment_mapping_evening() -> None:
    """Hours 18-23 → EVENING."""
    w = _make_world()
    for h in range(18, 24):
        w.hour = h
        w._sync_time_from_hour()
        assert w.time is TimeOfDay.EVENING, f"hour {h}"


def test_segment_mapping_night() -> None:
    """Hours 0-5 → NIGHT."""
    w = _make_world()
    for h in range(0, 6):
        w.hour = h
        w._sync_time_from_hour()
        assert w.time is TimeOfDay.NIGHT, f"hour {h}"

"""Tests for the in-game message throttle."""

import pytest

from nhc.rendering.message_throttle import MessageThrottle


class TestMessageThrottle:
    def test_first_message_passes_through(self):
        t = MessageThrottle()
        assert t.feed("hello") == ["hello"]

    def test_distinct_consecutive_messages_pass_through(self):
        t = MessageThrottle()
        assert t.feed("a") == ["a"]
        assert t.feed("b") == ["b"]
        assert t.feed("c") == ["c"]

    def test_lone_trailing_duplicate_dropped_on_break(self):
        t = MessageThrottle()
        assert t.feed("a") == ["a"]
        assert t.feed("a") == []
        # only 1 pending — silently dropped
        assert t.feed("b") == ["b"]

    def test_two_trailing_duplicates_emit_rollup_on_break(self):
        t = MessageThrottle()
        assert t.feed("a") == ["a"]
        assert t.feed("a") == []
        assert t.feed("a") == []
        assert t.feed("b") == ["a (x2)", "b"]

    def test_sixth_duplicate_emits_rollup(self):
        t = MessageThrottle()
        assert t.feed("a") == ["a"]
        for _ in range(4):
            assert t.feed("a") == []
        assert t.feed("a") == ["a (x5)"]

    def test_long_run_emits_periodic_rollups(self):
        t = MessageThrottle()
        emitted: list[str] = []
        for _ in range(11):
            emitted.extend(t.feed("a"))
        # 1st raw, rollup at 6th, rollup at 11th
        assert emitted == ["a", "a (x5)", "a (x5)"]

    def test_break_after_one_trailing_post_rollup_drops_it(self):
        t = MessageThrottle()
        for _ in range(7):
            t.feed("a")
        # state after: emitted "a" + "a (x5)", 1 pending — dropped
        assert t.feed("b") == ["b"]

    def test_break_with_pending_emits_rollup_then_new(self):
        t = MessageThrottle()
        for _ in range(8):
            t.feed("a")
        # 2 pending after the (x5) rollup
        assert t.feed("b") == ["a (x2)", "b"]

    def test_alternating_messages_never_throttle(self):
        t = MessageThrottle()
        for i in range(20):
            text = "a" if i % 2 == 0 else "b"
            assert t.feed(text) == [text]

    def test_run_state_resets_after_break(self):
        t = MessageThrottle()
        for _ in range(6):
            t.feed("a")
        t.feed("b")
        # New run of 'a' starts fresh
        assert t.feed("a") == ["a"]
        for _ in range(4):
            assert t.feed("a") == []
        assert t.feed("a") == ["a (x5)"]

    def test_custom_group_size(self):
        t = MessageThrottle(group_size=3)
        assert t.feed("a") == ["a"]
        assert t.feed("a") == []
        assert t.feed("a") == []
        assert t.feed("a") == ["a (x3)"]

    def test_invalid_group_size_raises(self):
        with pytest.raises(ValueError):
            MessageThrottle(group_size=1)
        with pytest.raises(ValueError):
            MessageThrottle(group_size=0)

    def test_empty_string_treated_as_normal_message(self):
        t = MessageThrottle()
        assert t.feed("") == [""]
        assert t.feed("") == []
        assert t.feed("") == []
        assert t.feed("a") == [" (x2)", "a"]

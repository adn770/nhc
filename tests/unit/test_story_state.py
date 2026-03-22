"""Tests for story state tracking."""

from nhc.narrative.story import StoryState


class TestStoryState:
    def test_add_turn(self):
        state = StoryState(compress_interval=5)
        state.add_turn("You entered the crypt.")
        assert len(state.recent_narrative) == 1
        assert state.turn_counter == 1

    def test_needs_compression(self):
        state = StoryState(compress_interval=3)
        assert not state.needs_compression
        for i in range(3):
            state.add_turn(f"Turn {i}")
        assert state.needs_compression

    def test_empty_turn_ignored(self):
        state = StoryState()
        state.add_turn("")
        state.add_turn("   ")
        assert len(state.recent_narrative) == 0
        assert state.turn_counter == 0

    def test_initial_state(self):
        state = StoryState()
        assert state.summary == ""
        assert state.recent_narrative == []
        assert state.turn_counter == 0

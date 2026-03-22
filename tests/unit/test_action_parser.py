"""Tests for the JSON action plan parser."""

from nhc.narrative.parser import extract_json, parse_action_plan


class TestExtractJson:
    def test_plain_array(self):
        assert extract_json('[{"action": "wait"}]') == '[{"action": "wait"}]'

    def test_markdown_fences(self):
        text = '```json\n[{"action": "wait"}]\n```'
        assert extract_json(text) == '[{"action": "wait"}]'

    def test_trailing_text(self):
        text = 'Here is the plan: [{"action": "wait"}] Hope that helps!'
        result = extract_json(text)
        assert '"action": "wait"' in result

    def test_single_object(self):
        text = '{"action": "move", "direction": "north"}'
        result = extract_json(text)
        assert result.startswith("[")
        assert "move" in result

    def test_no_json(self):
        assert extract_json("I don't know what to do") is None


class TestParseActionPlan:
    def test_valid_plan(self):
        text = '[{"action": "move", "direction": "north"}]'
        plan = parse_action_plan(text)
        assert len(plan) == 1
        assert plan[0]["action"] == "move"

    def test_invalid_json(self):
        plan = parse_action_plan("not json at all")
        assert plan == [{"action": "wait"}]

    def test_max_three_actions(self):
        text = '[{"action":"wait"},{"action":"wait"},{"action":"wait"},{"action":"wait"}]'
        plan = parse_action_plan(text)
        assert len(plan) == 3

    def test_filters_invalid_actions(self):
        text = '[{"action": "fly_to_moon"}, {"action": "wait"}]'
        plan = parse_action_plan(text)
        assert len(plan) == 1
        assert plan[0]["action"] == "wait"

    def test_custom_action(self):
        text = '[{"action": "custom", "description": "listen at door", "check": {"ability": "wisdom", "dc": 12}}]'
        plan = parse_action_plan(text)
        assert plan[0]["action"] == "custom"
        assert plan[0]["check"]["ability"] == "wisdom"

    def test_impossible_action(self):
        text = '[{"action": "impossible", "reason": "No wings"}]'
        plan = parse_action_plan(text)
        assert plan[0]["action"] == "impossible"
        assert "wings" in plan[0]["reason"].lower()

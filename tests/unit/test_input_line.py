"""Tests for the text input widget."""

from nhc.rendering.terminal.input_line import TextInput


class TestTextInput:
    def test_insert(self):
        inp = TextInput()
        inp.insert("h")
        inp.insert("i")
        assert inp.text == "hi"
        assert inp.cursor == 2

    def test_backspace(self):
        inp = TextInput()
        inp.insert("a")
        inp.insert("b")
        inp.backspace()
        assert inp.text == "a"
        assert inp.cursor == 1

    def test_backspace_at_start(self):
        inp = TextInput()
        inp.backspace()
        assert inp.text == ""
        assert inp.cursor == 0

    def test_delete(self):
        inp = TextInput()
        inp.insert("a")
        inp.insert("b")
        inp.home()
        inp.delete()
        assert inp.text == "b"

    def test_cursor_movement(self):
        inp = TextInput()
        inp.insert("abc")
        assert inp.cursor == 3
        inp.move_left()
        assert inp.cursor == 2
        inp.move_left()
        inp.move_left()
        assert inp.cursor == 0
        inp.move_left()  # should not go below 0
        assert inp.cursor == 0
        inp.end()
        assert inp.cursor == 3
        inp.move_right()  # should not go past end
        assert inp.cursor == 3

    def test_home_end(self):
        inp = TextInput()
        inp.insert("hello")
        inp.home()
        assert inp.cursor == 0
        inp.end()
        assert inp.cursor == 5

    def test_clear(self):
        inp = TextInput()
        inp.insert("test")
        inp.clear()
        assert inp.text == ""
        assert inp.cursor == 0

    def test_submit(self):
        inp = TextInput()
        inp.insert("go north")
        result = inp.submit()
        assert result == "go north"
        assert inp.text == ""
        assert len(inp.history) == 1

    def test_submit_empty(self):
        inp = TextInput()
        result = inp.submit()
        assert result == ""
        assert len(inp.history) == 0

    def test_history_up_down(self):
        inp = TextInput()
        inp.insert("first")
        inp.submit()
        inp.insert("second")
        inp.submit()
        inp.history_up()
        assert inp.text == "second"
        inp.history_up()
        assert inp.text == "first"
        inp.history_down()
        assert inp.text == "second"
        inp.history_down()
        assert inp.text == ""  # back to empty

    def test_history_max(self):
        inp = TextInput(max_history=3)
        for i in range(5):
            inp.insert(f"cmd{i}")
            inp.submit()
        assert len(inp.history) == 3
        assert inp.history[0] == "cmd2"

    def test_insert_mid_text(self):
        inp = TextInput()
        inp.insert("a")
        inp.insert("c")
        inp.move_left()
        inp.insert("b")
        assert inp.text == "abc"
        assert inp.cursor == 2

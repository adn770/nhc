"""Tests for logging infrastructure."""

import logging
import os
import tempfile

from nhc.log_utils import (
    GameFormatter,
    TopicFilter,
    derive_topic,
    list_topics,
    setup_logging,
)


class TestDeriveTopic:
    def test_exact_match(self):
        assert derive_topic("nhc.core.game") == "game"
        assert derive_topic("nhc.rules.combat") == "combat"
        assert derive_topic("nhc.ai.behavior") == "ai"

    def test_prefix_match(self):
        assert derive_topic("nhc.rendering.terminal.renderer") == "render"
        assert derive_topic("nhc.entities.registry") == "registry"

    def test_fallback(self):
        topic = derive_topic("nhc.unknown.module")
        assert topic == "module"

    def test_strips_nhc_prefix(self):
        assert derive_topic("nhc.core.ecs") == "ecs"

    def test_truncates_long_fallback(self):
        topic = derive_topic("nhc.something.very_long_module_name")
        assert len(topic) <= 12


class TestTopicFilter:
    def _make_record(self, level, name="nhc.core.game"):
        record = logging.LogRecord(
            name=name, level=level, pathname="", lineno=0,
            msg="test", args=(), exc_info=None,
        )
        return record

    def test_info_always_passes(self):
        f = TopicFilter(enabled_topics=None)
        record = self._make_record(logging.INFO)
        assert f.filter(record) is True

    def test_warning_always_passes(self):
        f = TopicFilter(enabled_topics=None)
        record = self._make_record(logging.WARNING)
        assert f.filter(record) is True

    def test_debug_blocked_by_default(self):
        f = TopicFilter(enabled_topics=None)
        record = self._make_record(logging.DEBUG)
        assert f.filter(record) is False

    def test_debug_passes_with_all(self):
        f = TopicFilter(enabled_topics="all")
        record = self._make_record(logging.DEBUG)
        assert f.filter(record) is True

    def test_debug_passes_with_specific_topic(self):
        f = TopicFilter(enabled_topics="game")
        record = self._make_record(logging.DEBUG, name="nhc.core.game")
        assert f.filter(record) is True

    def test_debug_blocked_wrong_topic(self):
        f = TopicFilter(enabled_topics="combat")
        record = self._make_record(logging.DEBUG, name="nhc.core.game")
        assert f.filter(record) is False

    def test_sets_topic_on_record(self):
        f = TopicFilter(enabled_topics="all")
        record = self._make_record(logging.DEBUG, name="nhc.rules.combat")
        f.filter(record)
        assert record.topic == "combat"


class TestGameFormatter:
    def test_format_includes_topic(self):
        fmt = GameFormatter(use_color=False)
        record = logging.LogRecord(
            name="nhc.core.game", level=logging.INFO,
            pathname="", lineno=0, msg="hello", args=(), exc_info=None,
        )
        record.topic = "game"
        output = fmt.format(record)
        assert "game" in output
        assert "hello" in output

    def test_format_includes_elapsed(self):
        fmt = GameFormatter(use_color=False)
        record = logging.LogRecord(
            name="nhc.core.game", level=logging.INFO,
            pathname="", lineno=0, msg="test", args=(), exc_info=None,
        )
        record.topic = "game"
        output = fmt.format(record)
        assert "[" in output and "]" in output

    def test_exception_formatting(self):
        fmt = GameFormatter(use_color=False)
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            ei = sys.exc_info()
            output = fmt.formatException(ei)
            assert "ValueError" in output
            assert "test error" in output


class TestSetupLogging:
    def test_creates_log_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test.log")
            result = setup_logging(log_file=log_path)
            assert result == log_path
            assert os.path.exists(log_path)

    def test_writes_to_log_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test.log")
            setup_logging(log_file=log_path)
            test_logger = logging.getLogger("nhc.test")
            test_logger.info("hello from test")
            # Flush handlers
            for h in logging.getLogger().handlers:
                h.flush()
            with open(log_path) as f:
                content = f.read()
            assert "hello from test" in content

    def test_debug_filtered_at_info_level(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test.log")
            setup_logging(level=logging.INFO, log_file=log_path)
            test_logger = logging.getLogger("nhc.test")
            test_logger.debug("should not appear")
            test_logger.info("should appear")
            for h in logging.getLogger().handlers:
                h.flush()
            with open(log_path) as f:
                content = f.read()
            assert "should appear" in content

    def test_debug_with_verbose(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test.log")
            setup_logging(level=logging.DEBUG, log_file=log_path)
            test_logger = logging.getLogger("nhc.test")
            test_logger.debug("debug message")
            for h in logging.getLogger().handlers:
                h.flush()
            with open(log_path) as f:
                content = f.read()
            assert "debug message" in content

    def test_exception_logged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test.log")
            setup_logging(log_file=log_path)
            test_logger = logging.getLogger("nhc.test")
            try:
                raise RuntimeError("kaboom")
            except RuntimeError:
                test_logger.error("something broke", exc_info=True)
            for h in logging.getLogger().handlers:
                h.flush()
            with open(log_path) as f:
                content = f.read()
            assert "RuntimeError" in content
            assert "kaboom" in content
            assert "Traceback" in content

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "sub", "dir", "test.log")
            setup_logging(log_file=log_path)
            assert os.path.exists(log_path)

    def test_topic_filtering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test.log")
            setup_logging(
                level=logging.DEBUG,
                debug_topics="combat",
                log_file=log_path,
            )
            combat_logger = logging.getLogger("nhc.rules.combat")
            game_logger = logging.getLogger("nhc.core.game")
            combat_logger.debug("combat debug")
            game_logger.debug("game debug")
            for h in logging.getLogger().handlers:
                h.flush()
            with open(log_path) as f:
                content = f.read()
            assert "combat debug" in content
            assert "game debug" not in content


class TestListTopics:
    def test_returns_string(self):
        output = list_topics()
        assert isinstance(output, str)
        assert "combat" in output
        assert "ai" in output

    def test_includes_categories(self):
        output = list_topics()
        assert "Core" in output
        assert "Rules" in output
        assert "AI" in output

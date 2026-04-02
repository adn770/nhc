"""Logging utilities with topic-based filtering and file output.

Inspired by MDT's log_utils.py, adapted for a roguelike game.

Features:
- TOPIC_MAP: Maps module paths to short topic names (e.g. 'combat', 'ai')
- derive_topic(): Auto-derives topic from __name__
- TopicFilter: Filters DEBUG by topic; INFO+ always passes
- GameFormatter: Aligned output with elapsed time and topic column
- setup_logging(): Configures root logger with file + optional console output
- Always logs to file for post-mortem debugging
"""

import logging
import os
import sys
import time
from datetime import datetime

# Module-level start time for 0-based timestamps
_start_time: float | None = None


def get_elapsed_ms() -> int:
    """Get milliseconds elapsed since logging was initialized."""
    if _start_time is None:
        return 0
    return int((time.perf_counter() - _start_time) * 1000)


def _reset_start_time() -> None:
    global _start_time
    _start_time = time.perf_counter()


# ---------------------------------------------------------------------------
# TOPIC_MAP: module path suffix -> short topic name
# ---------------------------------------------------------------------------
TOPIC_MAP: dict[str, str] = {
    # Core
    "core.game": "game",
    "core.ecs": "ecs",
    "core.actions": "action",
    "core.events": "event",
    "core.save": "save",
    # Rules
    "rules.combat": "combat",
    "rules.advancement": "xp",
    "rules.loot": "loot",
    "rules.magic": "magic",
    # AI
    "ai.behavior": "ai",
    "ai.pathfinding": "pathfind",
    "ai.tactics": "tactics",
    # Dungeon
    "dungeon.classic": "dungeon",
    "dungeon.generator": "dungeon",
    "dungeon.loader": "loader",
    "dungeon.populator": "populate",
    # Entities
    "entities.registry": "registry",
    # Rendering
    "rendering.terminal.renderer": "render",
    "rendering.terminal.input": "input",
    "rendering.web_client": "webclient",
    # Web server
    "web.app": "webapp",
    "web.ws": "ws",
    "web.sessions": "sessions",
    # Autosave
    "core.autosave": "autosave",
    # Narrative / LLM
    "narrative.narrator": "narrative",
    "utils.llm": "llm",
    # Config / i18n
    "config": "config",
    "i18n": "i18n",
    # Utils
    "utils.fov": "fov",
    "utils.rng": "rng",
}

# Category descriptions for --list-topics
TOPIC_CATEGORIES: dict[str, list[tuple[str, str]]] = {
    "Core": [
        ("game", "Game loop and session management"),
        ("ecs", "Entity-component-system"),
        ("action", "Action resolution (move, attack, use item)"),
        ("event", "Event bus emission and handling"),
        ("save", "Save/load serialization"),
    ],
    "Rules": [
        ("combat", "Attack rolls, damage, death checks"),
        ("xp", "XP awards and level-ups"),
        ("loot", "Loot generation"),
        ("magic", "Spell and scroll effects"),
    ],
    "AI": [
        ("ai", "Creature behavior decisions"),
        ("pathfind", "Pathfinding"),
        ("tactics", "AI tactics"),
    ],
    "Dungeon": [
        ("dungeon", "Level generation"),
        ("loader", "YAML level loading"),
        ("populate", "Entity population"),
    ],
    "Web": [
        ("webapp", "Flask application and API routes"),
        ("ws", "WebSocket handler and game threads"),
        ("webclient", "Web client renderer"),
        ("sessions", "Session manager"),
        ("autosave", "Autosave/restore system"),
    ],
    "Other": [
        ("render", "Terminal rendering"),
        ("narrative", "LLM narrative generation"),
        ("llm", "LLM backend communication"),
        ("registry", "Entity registry"),
        ("fov", "Field of view"),
    ],
}


def derive_topic(name: str) -> str:
    """Derive short topic from __name__ module path.

    Args:
        name: Module __name__ (e.g. 'nhc.core.game')

    Returns:
        Short topic string (e.g. 'game')
    """
    key = name.removeprefix("nhc.")

    # Exact match
    if key in TOPIC_MAP:
        return TOPIC_MAP[key]

    # Longest prefix match
    best: tuple[str, str] | None = None
    for prefix, topic in TOPIC_MAP.items():
        if key.startswith(prefix):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, topic)
    if best:
        return best[1]

    # Fallback: last segment, truncated
    return name.rsplit(".", 1)[-1][:12]


class TopicFilter(logging.Filter):
    """Filters log records based on topic.

    - INFO+ messages always pass.
    - DEBUG messages pass only if the topic is enabled.
    """

    def __init__(self, enabled_topics: str | None = None):
        super().__init__()
        self.enable_all = False
        self.enabled: set[str] = set()
        if enabled_topics:
            topics = [t.strip() for t in enabled_topics.split(",") if t.strip()]
            if "all" in topics:
                self.enable_all = True
            self.enabled = {t for t in topics if t != "all"}

    def filter(self, record: logging.LogRecord) -> bool:
        topic = getattr(record, "topic", None) or derive_topic(record.name)
        record.topic = topic

        if record.levelno > logging.DEBUG:
            return True

        if self.enable_all:
            return True
        return bool(self.enabled and topic in self.enabled)


class GameFormatter(logging.Formatter):
    """Aligned log output with elapsed time and topic column."""

    def __init__(self, use_color: bool = False):
        super().__init__()
        if use_color:
            self.COLORS = {
                logging.DEBUG: "\033[38;5;252m",
                logging.INFO: "\033[38;5;111m",
                logging.WARNING: "\033[38;5;229m",
                logging.ERROR: "\033[38;5;210m",
                logging.CRITICAL: "\033[38;5;217m",
            }
            self.BOLD = "\033[1m"
            self.RESET = "\033[0m"
        else:
            self.COLORS = {
                level: ""
                for level in [
                    logging.DEBUG, logging.INFO, logging.WARNING,
                    logging.ERROR, logging.CRITICAL,
                ]
            }
            self.BOLD = ""
            self.RESET = ""

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, self.RESET)
        level_name = record.levelname[:5]

        elapsed_ms = get_elapsed_ms()
        elapsed_str = f"{elapsed_ms // 1000:4d}.{elapsed_ms % 1000:03d}"

        topic = getattr(record, "topic", None) or derive_topic(record.name)

        prefix = (
            f"[{elapsed_str}] "
            f"{color}{level_name:<5}{self.RESET}:"
            f"{self.BOLD}{topic:<10}{self.RESET}: "
        )

        formatted = super().format(record)
        lines = formatted.split("\n")
        return "\n".join(f"{prefix}{line}" for line in lines)

    def formatException(self, ei: tuple) -> str:
        """Format exception with full traceback."""
        import traceback
        return "".join(traceback.format_exception(*ei)).rstrip()


def _default_log_path() -> str:
    """Return default log file path: debug/nhc.log or fallback."""
    # Three dirname calls: nhc/utils/log.py → nhc/utils → nhc → project root
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    debug_dir = os.path.join(project_root, "debug")
    try:
        os.makedirs(debug_dir, exist_ok=True)
        return os.path.join(debug_dir, "nhc.log")
    except OSError:
        pass
    # Fallback: NHC_DATA_DIR or /tmp
    data_dir = os.environ.get("NHC_DATA_DIR")
    if data_dir:
        return os.path.join(data_dir, "nhc.log")
    return os.path.join("/tmp", "nhc.log")


def setup_logging(
    level: int = logging.INFO,
    debug_topics: str | None = None,
    log_file: str | None = None,
    console_output: bool = False,
) -> str:
    """Configure logging with topic-aware filtering.

    Always writes to a log file (default: debug/nhc.log).
    Console output is off by default (game uses fullscreen terminal).

    Args:
        level: Base log level. DEBUG enables all topics unless
               debug_topics narrows it.
        debug_topics: Comma-separated topic list (e.g. 'combat,ai').
                      Use 'all' to enable all DEBUG.
        log_file: Path to write logs. Defaults to debug/nhc.log.
        console_output: Enable stderr console handler (for non-TUI use).

    Returns:
        Path to the log file being written.
    """
    _reset_start_time()

    root = logging.getLogger()

    # Remove existing handlers
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()

    # Allow DEBUG through root; filters control visibility
    root.setLevel(logging.DEBUG)

    # Build effective topic string
    # --verbose without --debug-topics enables all; with --debug-topics
    # only those specific topics get DEBUG
    effective_topics = debug_topics or ""
    if level <= logging.DEBUG and not effective_topics:
        effective_topics = "all"

    # File handler (always enabled)
    log_path = log_file or _default_log_path()
    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setFormatter(GameFormatter(use_color=False))
    # File always gets everything at the configured level
    file_filter = TopicFilter(enabled_topics=effective_topics or "all")
    file_handler.addFilter(file_filter)
    root.addHandler(file_handler)

    # Console handler (opt-in, for debugging outside the TUI)
    if console_output:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(GameFormatter(use_color=True))
        console_handler.setLevel(level)
        console_filter = TopicFilter(enabled_topics=effective_topics or None)
        console_handler.addFilter(console_filter)
        root.addHandler(console_handler)

    # Silence noisy libraries
    for lib in ("urllib3", "asyncio", "httpcore", "httpx"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    # Log session start
    logger = logging.getLogger("nhc")
    logger.info(
        "NHC logging started — %s — log file: %s",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        log_path,
    )

    return log_path


def list_topics() -> str:
    """Return formatted string of all available topics."""
    lines = ["Available debug topics:", ""]
    for category, topics in TOPIC_CATEGORIES.items():
        lines.append(f"  {category}:")
        for short_name, description in topics:
            lines.append(f"    {short_name:<12} {description}")
        lines.append("")
    lines.append("Usage:")
    lines.append("  --debug-topics combat,ai   Enable specific topics")
    lines.append("  --debug-topics all         Enable all topics")
    lines.append("  --verbose                  Enable all DEBUG output")
    lines.append("")
    return "\n".join(lines)

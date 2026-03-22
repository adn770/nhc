#!/usr/bin/env python3
"""NHC — Nethack-like Crawler.

Main entry point. Configures LLM backend, loads config, and launches the game.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from nhc.config import ConfigManager
from nhc.core.game import Game
from nhc.llm import create_backend
from nhc.log_utils import list_topics, setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NHC — A roguelike dungeon crawler with LLM narrative",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # LLM backend configuration
    llm_group = parser.add_argument_group("LLM backend")
    llm_group.add_argument(
        "-p", "--provider",
        choices=["ollama", "mlx", "anthropic", "none"],
        help="LLM provider (default: from config or 'none')",
    )
    llm_group.add_argument(
        "-m", "--model",
        help="Model name or path",
    )
    llm_group.add_argument(
        "-u", "--url",
        help="API URL (for ollama/anthropic)",
    )
    llm_group.add_argument(
        "--temp",
        type=float,
        help="Temperature for generation",
    )
    llm_group.add_argument(
        "--ctx",
        type=int,
        help="Context window size",
    )
    llm_group.add_argument(
        "--api-key",
        help="API key (for anthropic provider)",
    )

    # Game options
    game_group = parser.add_argument_group("Game options")
    game_group.add_argument(
        "--seed",
        type=int,
        help="RNG seed for reproducibility",
    )
    game_group.add_argument(
        "--level",
        help="Load a specific level file (YAML)",
    )
    game_group.add_argument(
        "--generate", "-G",
        action="store_true",
        help="Generate a random dungeon instead of loading a level file",
    )
    game_group.add_argument(
        "--lang",
        choices=["en", "ca", "es"],
        default=None,
        help="Game language (default: en, or from ~/.nhcrc)",
    )
    game_group.add_argument(
        "--colors",
        choices=["256", "16"],
        default=None,
        help="Color mode: 256 (default, truecolor) or 16 (classic)",
    )
    game_group.add_argument(
        "--mode",
        choices=["typed", "classic"],
        default=None,
        help="Gameplay mode: typed (LLM GM) or classic (roguelike keys)",
    )
    game_group.add_argument(
        "--no-narrative",
        action="store_true",
        help="Disable LLM narrative (equivalent to --provider none)",
    )

    # Logging options
    log_group = parser.add_argument_group("Logging")
    log_group.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG logging for all topics",
    )
    log_group.add_argument(
        "--log-file",
        help="Log file path (default: debug/nhc.log)",
    )
    log_group.add_argument(
        "--debug-topics",
        help="Comma-separated debug topics (e.g. 'combat,ai')",
    )
    log_group.add_argument(
        "--list-topics",
        action="store_true",
        help="List available debug topics and exit",
    )

    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    # --list-topics: print and exit
    if args.list_topics:
        print(list_topics())
        return 0

    # Setup logging (always writes to file)
    log_level = logging.DEBUG if args.verbose else logging.INFO
    log_path = setup_logging(
        level=log_level,
        debug_topics=args.debug_topics,
        log_file=args.log_file,
    )

    # Load config: defaults → ~/.nhcrc → CLI args
    config = ConfigManager()
    config.load()

    # CLI overrides
    cli_overrides = {}
    if args.provider:
        cli_overrides["provider"] = args.provider
    if args.model:
        cli_overrides["model"] = args.model
    if args.url:
        cli_overrides["url"] = args.url
    if args.temp is not None:
        cli_overrides["temp"] = args.temp
    if args.ctx is not None:
        cli_overrides["ctx"] = args.ctx
    if args.api_key:
        cli_overrides["api_key"] = args.api_key
    if args.no_narrative:
        cli_overrides["provider"] = "none"
    if args.colors:
        cli_overrides["colors"] = args.colors
    if args.mode:
        cli_overrides["mode"] = args.mode

    merged = config.merge(cli_overrides)

    # Initialize i18n (CLI --lang overrides config lang)
    from nhc.i18n import init as i18n_init
    lang = merged.get("lang", "en")
    if args.lang:
        lang = args.lang
    i18n_init(lang)

    # Color / gameplay mode
    color_mode = merged.get("colors", "256")
    game_mode = merged.get("mode", "classic")

    # Auto-detect LLM provider for typed mode
    if game_mode == "typed" and merged.get("provider", "none") == "none":
        merged["provider"] = "auto"

    # Create LLM backend (or None if provider is "none")
    backend = create_backend(merged)

    logger.info("Starting game (seed=%s, colors=%s, log=%s)",
                args.seed, color_mode, log_path)

    # Create and run game
    game = Game(backend=backend, seed=args.seed, color_mode=color_mode,
                game_mode=game_mode)
    try:
        if args.generate:
            await game.initialize(generate=True)
        else:
            level_path = args.level
            if not level_path:
                level_path = str(
                    Path(__file__).parent / "levels" / "test_level.yaml",
                )
            await game.initialize(level_path=level_path)
        await game.run()
    except Exception:
        logger.critical("Unhandled exception in game loop", exc_info=True)
        raise
    finally:
        logger.info("Game shutting down (turn=%d)", game.turn)
        await game.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

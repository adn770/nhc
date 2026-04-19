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
from nhc.hexcrawl.mode import add_mode_args, gamemode_from_args
from nhc.utils.llm import create_backend
from nhc.utils.log import list_topics, setup_logging

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
        choices=["auto", "ollama", "mlx", "anthropic", "none"],
        help="LLM provider: auto (MLX on Apple Silicon, else ollama), "
             "ollama, mlx, anthropic, or none (default: auto in typed mode)",
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
        "--theme",
        choices=["basic", "modern", "experimental"],
        default=None,
        help="Rendering theme (default: modern)",
    )
    game_group.add_argument(
        "--mode",
        choices=["typed", "classic"],
        default=None,
        help="Gameplay mode: typed (LLM GM) or classic (roguelike keys)",
    )
    game_group.add_argument(
        "--god",
        action="store_true",
        help="God mode: invulnerable, for exploration/testing",
    )
    game_group.add_argument(
        "--no-narrative",
        action="store_true",
        help="Disable LLM narrative (equivalent to --provider none)",
    )
    game_group.add_argument(
        "--reset",
        action="store_true",
        help="Start a new game, ignoring any autosave",
    )
    game_group.add_argument(
        "--shape-variety",
        type=float,
        default=None,
        help="Room shape variety 0.0-1.0 (default: 0.3, scales with depth)",
    )
    add_mode_args(
        game_group,
        default_world="dungeon",
        default_difficulty="medium",
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
    if args.shape_variety is not None:
        cli_overrides["shape_variety"] = args.shape_variety

    merged = config.merge(cli_overrides)

    # Initialize i18n (CLI --lang overrides config lang)
    from nhc.i18n import init as i18n_init
    lang = merged.get("lang", "en")
    if args.lang:
        lang = args.lang
    i18n_init(lang)

    # Color mode + input style
    color_mode = merged.get("colors", "256")
    style = merged.get("mode", "classic")

    # Create LLM backend (or None if provider is "none")
    backend = create_backend(merged)

    logger.info("Starting game (seed=%s, colors=%s, log=%s)",
                args.seed, color_mode, log_path)

    # Create terminal renderer
    from nhc.rendering.terminal.renderer import TerminalRenderer
    theme = args.theme or merged.get("theme", None)
    client = TerminalRenderer(
        color_mode=color_mode, style=style, theme=theme,
    )

    # Create and run game
    god_mode = args.god or merged.get("god", False)
    shape_variety = merged.get("shape_variety", 0.3)
    world_mode = gamemode_from_args(args)
    game = Game(client=client, backend=backend, seed=args.seed,
                style=style, god_mode=god_mode,
                reset=args.reset, shape_variety=shape_variety,
                world_mode=world_mode)
    try:
        if args.generate:
            game.initialize(generate=True)
        else:
            level_path = args.level
            if not level_path:
                level_path = str(
                    Path(__file__).parent / "levels" / "test_level.yaml",
                )
            game.initialize(level_path=level_path)
        # Typed mode generates an LLM intro narration once the world
        # is ready. Classic mode is a no-op here.
        await game.generate_intro_narration()
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

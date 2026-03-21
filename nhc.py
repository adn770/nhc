#!/usr/bin/env python3
"""NHC — Nethack-like Crawler.

Main entry point. Configures LLM backend, loads config, and launches the game.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from nhc.config import ConfigManager
from nhc.core.game import Game
from nhc.llm import create_backend


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
        "--no-narrative",
        action="store_true",
        help="Disable LLM narrative (equivalent to --provider none)",
    )

    return parser.parse_args()


async def main() -> int:
    args = parse_args()

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

    merged = config.merge(cli_overrides)

    # Initialize i18n (CLI --lang overrides config lang)
    from nhc.i18n import init as i18n_init
    lang = merged.get("lang", "en")
    if args.lang:
        lang = args.lang
    i18n_init(lang)

    # Create LLM backend (or None if provider is "none")
    backend = create_backend(merged)

    # Create and run game
    game = Game(backend=backend, seed=args.seed)
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
    finally:
        await game.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""Tests for the web app's generation pool wiring.

The Flask factory must:
- Expose a ProcessPoolExecutor for dungeon generation, sized via
  NHC_GEN_WORKERS (default: os.cpu_count()).
- Call EntityRegistry.discover_all() exactly once at startup, not on
  every game creation.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from unittest.mock import patch

from nhc.web.app import create_app
from nhc.web.config import WebConfig


class TestGenPool:
    def test_create_app_exposes_gen_pool(self, tmp_path):
        app = create_app(WebConfig(data_dir=tmp_path, max_sessions=2))
        try:
            pool = app.config.get("GEN_POOL")
            assert isinstance(pool, ProcessPoolExecutor)
        finally:
            app.config["GEN_POOL"].shutdown(wait=True)

    def test_pool_size_defaults_to_cpu_count(self, tmp_path):
        app = create_app(WebConfig(data_dir=tmp_path, max_sessions=2))
        try:
            pool = app.config["GEN_POOL"]
            expected = os.cpu_count() or 1
            # ProcessPoolExecutor stores _max_workers
            assert pool._max_workers == expected
        finally:
            app.config["GEN_POOL"].shutdown(wait=True)

    def test_pool_size_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NHC_GEN_WORKERS", "3")
        app = create_app(WebConfig(data_dir=tmp_path, max_sessions=2))
        try:
            assert app.config["GEN_POOL"]._max_workers == 3
        finally:
            app.config["GEN_POOL"].shutdown(wait=True)

    def test_pool_can_generate_level(self, tmp_path):
        """End-to-end: pool worker produces a valid Level."""
        from nhc.dungeon.generator import GenerationParams
        from nhc.dungeon.model import Level

        app = create_app(WebConfig(data_dir=tmp_path, max_sessions=2))
        try:
            pool = app.config["GEN_POOL"]
            from nhc.dungeon.pipeline import generate_level
            params = GenerationParams(
                width=40, height=30, depth=1, seed=7, theme="dungeon"
            )
            future = pool.submit(generate_level, params)
            level = future.result(timeout=30)
            assert isinstance(level, Level)
            assert len(level.rooms) > 0
        finally:
            app.config["GEN_POOL"].shutdown(wait=True)


class TestEntityDiscoveryHoisted:
    def test_discover_all_called_once_in_create_app(self, tmp_path):
        """EntityRegistry.discover_all() must be called in create_app,
        not on every game.initialize() call."""
        with patch(
            "nhc.entities.registry.EntityRegistry.discover_all"
        ) as mock_discover:
            app = create_app(WebConfig(data_dir=tmp_path, max_sessions=2))
            try:
                assert mock_discover.call_count >= 1
            finally:
                app.config["GEN_POOL"].shutdown(wait=True)

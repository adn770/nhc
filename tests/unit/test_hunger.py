"""Tests for the hunger mechanics."""

from nhc.entities.components import Health, Hunger
from nhc.core.game_ticks import (
    _hunger_state, tick_hunger,
    _SATIATED_THRESHOLD, _HUNGRY_THRESHOLD, _STARVING_THRESHOLD,
)


class TestHungerState:
    def test_satiated(self):
        assert _hunger_state(1100) == "satiated"

    def test_normal(self):
        assert _hunger_state(900) == "normal"
        assert _hunger_state(301) == "normal"

    def test_hungry(self):
        assert _hunger_state(300) == "hungry"
        assert _hunger_state(101) == "hungry"

    def test_starving(self):
        assert _hunger_state(100) == "starving"
        assert _hunger_state(0) == "starving"

    def test_thresholds_consistent(self):
        assert _SATIATED_THRESHOLD > _HUNGRY_THRESHOLD
        assert _HUNGRY_THRESHOLD > _STARVING_THRESHOLD


class TestHungerComponent:
    def test_default_values(self):
        h = Hunger()
        assert h.current == 900
        assert h.maximum == 1200
        assert h.prev_state == "normal"
        assert h.str_penalty == 0
        assert h.dex_penalty == 0


class TestTickHunger:
    def _make_game(self, hunger_current=900, turn=1):
        """Create a minimal mock game with a player that has Hunger."""
        from unittest.mock import MagicMock
        from nhc.core.ecs import World

        game = MagicMock()
        game.world = World()
        game.turn = turn

        pid = game.world.create_entity({
            "Hunger": Hunger(current=hunger_current),
            "Health": Health(current=10, maximum=10),
        })
        game.player_id = pid
        return game

    def test_decrements_each_turn(self):
        game = self._make_game(hunger_current=500)
        tick_hunger(game)
        h = game.world.get_component(game.player_id, "Hunger")
        assert h.current == 499

    def test_clamps_at_zero(self):
        game = self._make_game(hunger_current=0)
        tick_hunger(game)
        h = game.world.get_component(game.player_id, "Hunger")
        assert h.current == 0

    def test_normal_no_penalties(self):
        game = self._make_game(hunger_current=500)
        tick_hunger(game)
        h = game.world.get_component(game.player_id, "Hunger")
        assert h.str_penalty == 0
        assert h.dex_penalty == 0

    def test_hungry_applies_penalties(self):
        game = self._make_game(hunger_current=200)
        tick_hunger(game)
        h = game.world.get_component(game.player_id, "Hunger")
        assert h.str_penalty == -1
        assert h.dex_penalty == -1

    def test_starving_applies_heavy_penalties(self):
        game = self._make_game(hunger_current=50)
        tick_hunger(game)
        h = game.world.get_component(game.player_id, "Hunger")
        assert h.str_penalty == -2
        assert h.dex_penalty == -2

    def test_starving_hp_drain(self):
        game = self._make_game(hunger_current=50, turn=10)
        tick_hunger(game)
        hp = game.world.get_component(game.player_id, "Health")
        assert hp.current == 9  # lost 1 HP (turn 10 % 5 == 0)

    def test_starving_no_drain_off_cycle(self):
        game = self._make_game(hunger_current=50, turn=7)
        tick_hunger(game)
        hp = game.world.get_component(game.player_id, "Health")
        assert hp.current == 10  # no drain (turn 7 % 5 != 0)

    def test_transition_message_hungry(self):
        game = self._make_game(hunger_current=301)
        h = game.world.get_component(game.player_id, "Hunger")
        h.prev_state = "normal"
        tick_hunger(game)  # 301→300, enters hungry
        game.renderer.add_message.assert_called()

    def test_transition_message_starving(self):
        game = self._make_game(hunger_current=101)
        h = game.world.get_component(game.player_id, "Hunger")
        h.prev_state = "hungry"
        tick_hunger(game)  # 101→100, enters starving
        game.renderer.add_message.assert_called()

    def test_satiated_heals(self):
        game = self._make_game(hunger_current=1100, turn=20)
        hp = game.world.get_component(game.player_id, "Health")
        hp.current = 8  # damaged
        tick_hunger(game)
        assert hp.current == 9  # healed 1

    def test_penalties_clear_when_fed(self):
        game = self._make_game(hunger_current=200)
        tick_hunger(game)
        h = game.world.get_component(game.player_id, "Hunger")
        assert h.str_penalty == -1
        # Simulate eating — hunger goes back to normal
        h.current = 500
        tick_hunger(game)
        assert h.str_penalty == 0
        assert h.dex_penalty == 0

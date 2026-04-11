"""Tests for the shared retreat-step helper.

The helper picks the adjacent step that maximises Chebyshev
distance from a given threat. It is reused by both unhired
adventurers (henchman_ai) and morale-broken monsters that have
flipped into the fleeing state.
"""

import pytest

from nhc.ai.retreat import best_retreat_step


pytestmark = pytest.mark.core


def _all_walkable(x: int, y: int) -> bool:
    return True


class TestBestRetreatStep:
    def test_steps_strictly_away_in_open_field(self):
        # Threat at (5,5), entity at (6,5). Current cheb=1.
        # The retreat must strictly increase distance and the
        # picked tile must be on the +x side of the entity.
        from nhc.utils.spatial import chebyshev

        step = best_retreat_step(
            (6, 5), (5, 5), _all_walkable,
        )
        assert step is not None
        dx, dy = step
        nx, ny = 6 + dx, 5 + dy
        assert chebyshev(nx, ny, 5, 5) > 1
        assert dx == 1  # only +x moves can break out of cheb=1

    def test_diagonal_retreat_strictly_improves(self):
        # Threat at (5,5), entity at (6,6). Current cheb=1.
        # Any step that pushes one axis to abs delta = 2 wins.
        # The helper guarantees a strictly larger chebyshev,
        # not a particular tile (chebyshev is a max of axes).
        from nhc.utils.spatial import chebyshev

        step = best_retreat_step(
            (6, 6), (5, 5), _all_walkable,
        )
        assert step is not None
        dx, dy = step
        nx, ny = 6 + dx, 6 + dy
        assert chebyshev(nx, ny, 5, 5) > 1

    def test_returns_none_when_no_improvement(self):
        # Threat is far enough that no adjacent tile increases the
        # current chebyshev distance — this is "still cornered".
        # Place threat at (0,0), entity at (5,5): chebyshev=5,
        # but step (1,1) goes to (6,6) → cheb=6 → improvement.
        # To force "no improvement", surround entity with walls.
        def only_corner(x: int, y: int) -> bool:
            return False
        step = best_retreat_step(
            (5, 5), (0, 0), only_corner,
        )
        assert step is None

    def test_chooses_walkable_tile(self):
        # Threat at (5,5), entity at (6,5). The "best" tile (7,5)
        # is blocked, but (7,6) and (7,4) remain — both improve
        # distance from cheb=1 to cheb=2.
        def blocked_east(x: int, y: int) -> bool:
            return not (x == 7 and y == 5)
        step = best_retreat_step(
            (6, 5), (5, 5), blocked_east,
        )
        assert step is not None
        nx, ny = 6 + step[0], 6 + 0  # noqa
        # Step must move us to a walkable tile that isn't (7,5)
        nx = 6 + step[0]
        ny = 5 + step[1]
        assert blocked_east(nx, ny)
        # And it must increase distance to threat
        from nhc.utils.spatial import chebyshev
        assert chebyshev(nx, ny, 5, 5) > 1

    def test_does_not_pick_no_op(self):
        # The (0, 0) step is excluded from candidates.
        step = best_retreat_step(
            (5, 5), (0, 0), _all_walkable,
        )
        assert step != (0, 0)

    def test_returns_none_when_only_no_op_available(self):
        # All 8 neighbours blocked → cornered.
        def only_self(x: int, y: int) -> bool:
            return False
        step = best_retreat_step(
            (5, 5), (0, 0), only_self,
        )
        assert step is None

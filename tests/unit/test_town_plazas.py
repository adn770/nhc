"""Unit tests for two-tier plaza stamping (Phase 3).

Exercises ``nhc.sites.town.stamp_plazas`` in isolation on a synthetic
surface: a big plaza is a full cobblestone square with a tier/biome
fountain; a small plaza is a well on a paved collar with a grass apron
and a tree. The auto-shrunk big plaza keeps its fountain.

See design/town_generator.md §3.2 (D7, B3, Q1, Q6).
"""

from nhc.dungeon.model import Level, Rect, SurfaceType, Terrain
from nhc.hexcrawl.model import Biome
from nhc.sites._town_bsp import Plaza
from nhc.sites.town import stamp_plazas


def _surface(width: int = 40, height: int = 40) -> Level:
    return Level.create_empty("t", "t", 0, width, height)


def _features(surface: Level) -> list[str]:
    return [
        tile.feature
        for row in surface.tiles
        for tile in row
        if tile.feature is not None
    ]


def test_big_plaza_full_cobblestone_with_fountain():
    surface = _surface()
    stamp_plazas(surface, [Plaza(Rect(5, 5, 7, 7), "big")], "town", None)
    for x in range(5, 12):
        for y in range(5, 12):
            assert surface.tiles[y][x].surface_type is SurfaceType.STREET
    assert _features(surface) == ["fountain"]


def test_city_big_plaza_uses_large_fountain():
    surface = _surface()
    stamp_plazas(surface, [Plaza(Rect(5, 5, 11, 11), "big")], "city", None)
    assert _features(surface) == ["fountain_large"]


def test_village_big_plaza_is_a_fountain_not_a_well():
    # B3: villages are re-tiered well -> fountain.
    surface = _surface()
    stamp_plazas(surface, [Plaza(Rect(5, 5, 7, 7), "big")], "village", None)
    assert _features(surface) == ["fountain"]


def test_auto_shrunk_big_plaza_keeps_fountain():
    # Q6: a 5x5 big plaza (auto-shrunk) still stamps a fountain.
    surface = _surface()
    stamp_plazas(surface, [Plaza(Rect(5, 5, 5, 5), "big")], "village", None)
    feats = _features(surface)
    assert feats == ["fountain"]
    for x in range(5, 10):
        for y in range(5, 10):
            assert surface.tiles[y][x].surface_type is SurfaceType.STREET


def test_small_plaza_well_collar_apron_and_tree():
    surface = _surface()
    stamp_plazas(surface, [Plaza(Rect(10, 10, 5, 5), "small")], "city", None)
    cx, cy = 12, 12
    # Well at centre on a paved collar.
    assert surface.tiles[cy][cx].feature == "well"
    assert surface.tiles[cy][cx].surface_type is SurfaceType.STREET
    # Apron corner is grass garden, not cobblestone.
    assert surface.tiles[10][10].surface_type is SurfaceType.GARDEN
    assert surface.tiles[10][10].terrain is Terrain.GRASS
    feats = set(_features(surface))
    assert "well" in feats and "tree" in feats


def test_biome_feature_variant_square():
    surface = _surface()
    stamp_plazas(
        surface, [Plaza(Rect(5, 5, 7, 7), "big")], "town", Biome.MOUNTAIN,
    )
    assert _features(surface) == ["fountain_square"]


def test_multiple_plazas_each_stamped():
    surface = _surface(60, 30)
    plazas = [
        Plaza(Rect(2, 2, 11, 11), "big"),
        Plaza(Rect(20, 2, 5, 5), "small"),
        Plaza(Rect(40, 2, 5, 5), "small"),
    ]
    stamp_plazas(surface, plazas, "city", None)
    feats = _features(surface)
    assert feats.count("fountain_large") == 1
    assert feats.count("well") == 2
    assert feats.count("tree") == 2

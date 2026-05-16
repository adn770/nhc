# Roof tile patterns

How building roofs are textured in the IR rasteriser. This is the *what* and *why*; the
executing plan lives (transiently) at `~/src/plans/roof-pattern-redesign.md`.

## Model

A roof is drawn in two separable layers:

1. **Geometry** — the silhouette, the planes (gable halves / pyramid facets / dome
   rings), per-plane sun/shadow shading, and the ridge lines. Owned by the per-style
   draw functions in `crates/nhc-render/src/transform/png/roof.rs`.
2. **Texture** — the tile pattern painted on top, clipped to the silhouette. Owned by
   the `paint_<pattern>` functions.

Geometry never draws tiles. Texture never draws silhouette/ridge. This separation is
what lets every pattern apply to every style.

## Styles (geometry)

| Style    | Planes                                  | Ridge                        |
|----------|-----------------------------------------|------------------------------|
| Simple   | 1 flat plane                            | none                         |
| Gable    | 2 halves split on the long axis         | 1 line along the long axis   |
| Pyramid  | N triangular facets from the centroid   | N spokes centroid→vertices   |
| Dome     | concentric shrinking rings              | none                         |

Style is chosen in `nhc/rendering/emit/roof.py:_pick_style` from the region shape tag,
matching the legacy shape-driven dispatch (l_shape→Gable, square rect→Pyramid, wide/tall
rect→Gable, octagon/circle→Pyramid). The `WitchHat` cone was retired; forest watchtowers
(`roof_material == "wood"`) take the shape-default Pyramid.

## Patterns (texture)

`Plain` is **removed** — every roof carries a real texture. The set:

| Pattern   | Look                                                                       |
|-----------|----------------------------------------------------------------------------|
| Shingle   | large, loose, heavily jittered running-bond; random per-tile shade. The     |
|           | default (FlatBuffers enum value 0). Replaces the old geometry-baked gable   |
|           | shingle drawing.                                                           |
| Slate     | fine, tight running-bond; *lightly* jittered shade/edge — crisp counterpoint |
|           | to Shingle, distinguished by scale + regularity, not by being flat.        |
| Fishscale | overlapping scallop discs in offset rows, each with a thin black outline.   |
| Thatch    | dense randomised strands, straw-like.                                       |

(`Pantile` — wavy Mediterranean S-curve bands — was retired; it read as confusing
texture and was dropped.)

Pattern is chosen in `nhc/rendering/emit/roof.py:_pick_sub_pattern`. Default-biome
buildings (brick/stone walls) map to **Shingle** so ordinary towns keep the organic
rooftop look. `roof_material` ("thatch"/"tile"/"slate"/"fishscale") and `wall_material`
(adobe→Thatch, wood→Thatch) override.

### Parity note

Before this redesign, brick/stone mapped to `Plain`, which on gable geometry rendered
as organic shingles. Remapping to `Shingle` keeps that *look* but the pixels are
re-laid through the new facet-oriented pattern path, so default-town roofs shift
slightly. This drift is intended, not a regression.

## Orientation

Patterns are oriented relative to the geometry, not the screen:

- **Gable / rect:** flat top-down read. The ridge is a divider; the pattern **mirrors
  across the ridge** between the two halves. No up-slope foreshortening.
- **Pyramid:** each facet's pattern is **rotated into that facet's local frame** —
  tile rows parallel to the facet's outer edge, "up" toward the centroid apex. The
  texture rotates facet-by-facet around the roof.
- **Dome:** the pattern follows the **concentric rings**, curving around rather than a
  straight grid.

### Plane-local frame

Each plane exposes a `(u, v) → screen` mapping. Pattern painters draw in plane-local
`(u, v)`; the frame carries orientation. This single seam also makes the **top-down vs
perspective** choice a one-parameter swap:

- *top-down* — affine fill of the plane polygon (uniform scale).
- *perspective* — same `(u, v)` texture with a vertical foreshortening (trapezoidal
  warp toward the ridge) baked into the frame mapping.

A `RoofProjection { TopDown, Foreshortened }` parameter therefore selects between the
two with one transform, not two code paths. (The projection default is an open product
decision; see the execution plan.)

## Catalog

`tests/samples/_samples/_catalog/roof_patterns.py` renders a styles × patterns matrix so
every combination is visible and regression-checked, rather than the historical
Pyramid-only page.

# Baked-in shadows: offline de-shadowing prototype (2026-10-10)

Trigger: user report of the ravine at 36.506422, -118.402437. Ridge to the east is about 1000 m higher; the USGS photo has its cast shadow baked in.

Data: USGS z16 (1.92 m/px) and Mapterhorn z15 DEM (about 1.9 m), both fetched through the unmodified `server/imagery.py` and `server/dem.py`. The DEM uses the same pixel grid as the imagery, with a 1.5 km pad. Windows are 1562 px (3 km). Scripts are in `prototype/` (numpy and Pillow only; scipy is not installed).

**Sun fit.** For each candidate azimuth (5° steps) and elevation (2.5° steps), on a 15 m grid:
- A horizon march toward the sun gives the cast mask; one march per azimuth serves all elevations.
- Score = signed r² of luminance against Lambert × lit, plus 0.5 × MCC of predicted shadow against dark pixels.
- An IoU term was tried first and dropped because it favoured low suns.
- A refine on the cast-shadow mask (MCC) at 7.7 m follows.

| Window | Fitted sun (az, el) | r² / MCC | How sharp |
|---|---|---|---|
| Ravine | 93, 33.5 | 0.63 / 0.44 | el 29.5–33.5, az 80–100 |
| Kern Plateau 36.20,-118.30 | 95, 15 unconstrained; 110, 30 with el ≥ 30 prior | 0.29 / 0.39 | elevation not constrained |
| Foothills 36.62,-119.05 | 177, 21 | 0.16 | gate off |
| Flat 35.40,-119.20 | none | 0.00 | gate off |

The ravine sun corresponds to about 07:50 solar time in May or August, consistent with NAIP's sun ≥ 30° rule. USGS is a mosaic of flights, so the sun must be fitted per region.

**Method A (physical relight).** Model per pixel: I_c = A_c (amb_c + sun_c · lam · lit) + haze_c.
1. Terrain terms (shadow mask and Lambert shading) on a 7.7 m grid.
2. Snap the mask to the image. Prior: the DEM mask blurred over 40 px, clipped to [0.03, 0.97]. Likelihood: two Gaussians in (log L, B/(R+G+B)) fitted on the confident interiors (separation 0.98). Then a guided filter (r = 2) and a 3× sharpening around 0.5. If separation is below 0.9, the cast term is turned off.
3. Haze: subtract 0.9 × the 0.5th percentile per channel, add it back afterwards.
4. Shadow-edge band, 4–16 px from the edge on both sides:
   - Measured shadow/sun ratio k = 0.135 / 0.139 / 0.307 (R/G/B).
   - From it, sky/sun ratio rho = k·lam_e/(1−k) = 0.070 / 0.072 / 0.197.
   - A global regression failed: the shadowed side was forest and the sunlit side granite.
5. Gain:
   - g = clip_{1/1.6..1.6}((rho+sin el)/(rho+lam)) · (rho+lam)/(rho+lam·lit).
   - Total gain capped at 10, all channels scaled together to keep the hue.
6. Clean-up in boosted pixels: chroma from a 7×7 mean, half 3×3 luminance denoise, soft shoulder above 0.8.

**Method B (gain matching).** Haze subtracted first. Within a 24 px band along the shadow edge, compare geometric means of shadowed and sunlit pixels per vegetation-index tercile, with terciles taken separately inside and outside the shadow. Local statistics use r = 96 px. Gains are smoothed and hue-capped.

**Results.**
- **Ravine, method A:** shadow removed at map scale with matched brightness and no visible edge. Remaining:
  - red/green speckle at full resolution;
  - lifted area slightly cool and flat (no tree shadows under sky light);
  - gully floors still dim (sky-view loss not modelled);
  - faint rims on small gully shadows.
- **Ravine, method B:** dark band at the edge, blotchy.
- **Hillside, method A:** mild, even lift; cast term gated off (separation 0.83). Method B: no change.
- **Flat, method A:** mean change 0.02 levels, 99th percentile 1. Method B: no change.

**Cost.**
- Full window: terrain 0.45 s, snap 0.85 s, relight 1.06 s.
- Per 256 px tile, values precomputed:
  - horizon: 11 ms steep, 0.5 ms flat (early exit);
  - relight: 20 ms for shadow-edge tiles, 7–11 ms otherwise, 1 ms when nothing changes.
- Region values: about 0.9 s per 9 km².
- Sun fit: 4 s per 9 km².

**Failure cases.**
- Uncertain sun without cast shadows; mitigated by the prior, an r² gate (≥ 0.25) and the Lambert cap.
- Mosaic seams between flights; check with z14 sub-block fits.
- Misregistration over 77 m, or a sun elevation error over 1°. This fails conservatively: shadow is left, nothing is wrongly brightened.
- Water and dark lava read as shadow; mask water out.
- ×8–10 noise in deep shadows; a gain cap of 5–6 is the conservative choice.
- Not modelled: sky-view, terrain bounce light, canopy self-shadowing.
- Tree and building shadows are left on purpose.
- EOX imagery untested.
- Method B depends on similar land cover across the shadow edge and needs a mask.

**Integration plan.**
- `server/deshadow.py`.
  - Per USGS z12 region: values cached as JSON under `<cache>/deshadow/usgs/12/x/y.json`, plus the shadow mask and Lambert grid as `.npz`.
  - Computed from z14 imagery and `Dem.sample` on a 15–30 m grid, in the background when an anchor is set (3–5 s per region).
- Per-tile `relight_tile`:
  - 8 px margin taken from neighbouring source tiles;
  - results kept in a second LRU and on disk as `imagery/usgs-ds<ver>/`.
- Hook: `Imagery(..., deshadow=obj)`, called in `_mosaic` for USGS only.
  - Uses raw tiles until the region's values are ready, then rebuilds the affected tiles.
  - Flag `--deshadow off|lambert|full`, default off.
  - With `full`, reduce the tone-curve shadow lift (tone about 0.5).
- Logging: per-region sun, gates and fit time; per-tile counts of the no-op / fast / edge paths.
- Tests (`server/tests/test_deshadow.py`):
  - `box()` against brute force; guided filter with no overshoot;
  - synthetic ridge scene with known sun, haze and JPEG: fit within 3° az / 1.5° el, relit ratio within 10 %, no pixel outside the shadow above 1.6× (halo test);
  - 20 px misregistration: snapped mask IoU ≥ 0.9;
  - flat DEM bitwise unchanged; low-r² region unchanged;
  - separation gate off on dark texture;
  - hue-preserving cap;
  - JSON cache round-trip and version-bump recompute;
  - flag off gives byte-identical `render()`;
  - slow timing test: < 25 ms per shadow-edge tile, < 3 ms per unchanged tile;
  - in-game check at the ravine at 08:00 and 16:00 game time.
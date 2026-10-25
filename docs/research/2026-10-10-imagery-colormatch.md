# Imagery colour seams: offline colour-match prototype (2026-10-10)

**Trigger.** User report at 36.998218, -110.102293 (Monument Valley, on the Arizona/Utah line at 37.0° N). The user described it as sitting on a colour border that stretches for miles: the AZ side is redder and darker, the UT side paler and yellower. Screenshot: `imagery_seams/seam1.png`.

**Cause.** USGS ImageryOnly is a mosaic of NAIP flights from different years and seasons. Each state is flown separately, so state lines (and other flight boundaries) are sharp colour steps.

At this spot the step is very large:

| Side | Lab (L\*, a\*, b\*) |
|---|---|
| UT | 67, 9, 29 |
| AZ | 52, 15, 19 |

Relative to Sentinel-2 the step is +58 / +90 / +45 % (R/G/B, linear light). Sentinel-2 shows no step there (ΔE 0.6 between the same bands).

The seam is not a perfectly straight pixel row. It sits at z16 rows 2298.4–2301.3 over 6 km, stepping by about 1 px every 1–2 km, with a 2–3 px blend/JPEG-ringing strip.

No game or MCP server was contacted. `mod/`, `server/` and `tools/` are unchanged.

Scripts are in the session scratchpad, `.../scratchpad/colormatch/`:

| Script | Purpose |
|---|---|
| `fetch.py` | data, via the unmodified `server/imagery.py` (its cache and its generic UA) |
| `cm.py`, `colormatch.py` | method |
| `experiment.py`, `synth.py`, `tile.py` | evaluation |
| `results.json`, `synth.json` | numbers |

Only numpy and Pillow are used.

## 1. Data

Three windows, each 7.8 × 7.8 km:

| Window | Centre |
|---|---|
| Seam | the user's point |
| Central Valley | 35.40, -119.20 |
| Baltimore | 39.29, -76.53 |

Sources:
- USGS z16: 256 tiles per window, 1.91 m/px.
- EOX S2 cloudless 2023 z14: 16 tiles, 7.6 m/px. 2016 was also fetched, to check how much the result depends on the S2 vintage.

The z14 grid is exactly the z16 grid at 4× (pixel-aligned, so there is no reprojection). The measured USGS↔S2 misregistration is 0 px at z14.

Metrics use the central 6 × 6 km.

## 2. Why the plain low-frequency transfer does not work

The plain transfer is `out = usgs · blur(s2)/blur(usgs)`.

A smooth gain cannot remove a sharp step. Just left and right of the seam, both pixels get almost the same gain, so the step ratio survives unchanged. Only the area within ~r of the seam changes, and that change turns into a ramp.

| Variant (seam window) | ΔE 200 m bands | ΔE 20 m bands | Survey step R/G/B, 20 m bands |
|---|---|---|---|
| before | 17.6 | 17.9 | +62 / +96 / +50 % |
| plain, r = 300 m | 11.4 | 17.0 | +57 / +91 / +47 % |
| plain, r = 600 m | 14.6 | 17.4 | +59 / +94 / +48 % |
| plain, r = 1000 m | 15.8 | 17.9 | +60 / +95 / +49 % |
| S2 itself (natural difference) | 0.58 | 0.47 | 0 by definition |

The figures `colormatch_seam_window.png` (panel 2) and `colormatch_seam_zoom.png` show this: the seam is still a hard line.

## 3. Method (proposed: "seam feather")

All operations run in linear light, per channel. They work on the S2 z14 grid ("cells" of 4 × 4 USGS px), then one band step runs at full resolution.

1. **Reliability weights.**
   - Base weights drop deep shadow and water (min luminance < 0.006 → 0.02), and snow or cloud present in only one source (bright and grey).
   - IRLS weights (τ = 0.25 in log units) are taken against a 30 m robust blur. Cast shadows, which differ in sun angle between NAIP and S2, become outliers this way.
2. **Survey-seam detection.**
   - Grid: 15 m (2× coarser than the cells), on `log usgs` and `log s2`.
   - Oriented step filter: 36 angles (5°). Each tested line covers 5 segments of 240 m, with 45 m bands on each side and a 1-cell gap.
   - Per segment: the USGS step minus the S2 step. Natural edges appear in both images; survey seams appear only in USGS.
   - Score = |median step| when all of these hold:
     - at least 75 % of the segments agree (cos > 0.7, at least half the magnitude);
     - the S2 step is small compared with the residual step (|D_s2| − 0.03 < 1.5 |D|; this kills natural edges that only differ in contrast).
   - Then NMS along the normal, hysteresis (0.12 / 0.042), and a component filter:
     - extent ≥ 1.5 km;
     - mean score ≥ 0.12;
     - step vector consistent along the line (median |D − D̃| / |D̃| ≤ 0.3: a flight seam has the same gain ratio everywhere; crop-change field edges do not).
3. **Sub-pixel seam line.**
   - Each seam cell fits the full-resolution USGS profile across the line: ±12 px across, averaged over 48 px along.
   - Change-point, then the centroid of the derivative, then a trimmed mean over neighbours within ±16 cells.
   - Accuracy against the measured 50 % crossing is ≤ 0.2 px.
4. **Correction field.** The cut is the seam dilated by 1 cell.
   - Local step: the domain-transform (recursive-filter) blur of the weighted usgs and s2 at σ_s = 300 m, **cut at the seams**, sampled 4 cells either side of each seam cell. Each side moves half way (`feather_split = 0.5`).
   - The half-steps are extended along each side with the same cut blur (300 m; 1500 m where the short one has no support).
   - They are faded with a Gaussian of the distance to the seam, σ_f = 1500 m.
   - Away from seams the gain is **exactly 1**. Nothing is pulled toward S2's palette.
5. **Full resolution.**
   - Outside a 3-cell band: bilinear ×4 of the coarse log gain.
   - Inside the band: each pixel takes its side's gain from its signed distance to the sub-pixel line (2 px ramp).
   - The |d| ≤ 1.5 px strip on the line is the mosaic's own blend row plus JPEG ringing, which no gain can fix. It is inpainted along the normal from the corrected pixels at d = ±2.5 px.
6. Clamp the gain to ±log 2. The server's tone LUT stays last.

Two other variants were also run, using the same cut blur:
- "full rel": local colour transfer `usgs · exp(−(Lsm − L̄))`, which matches the 500 m-scale colour *pattern* of S2 while keeping USGS' mean palette.
- "abs": full match to S2 colours.

## 4. Results

### Seam window (6 × 6 km)

| Variant | ΔE 200 m bands | ΔE 20 m bands | Survey step R/G/B, 20 m bands | Mean / p99 change (levels) | HF kept: log-std ratio / corr |
|---|---|---|---|---|---|
| before | 17.6 | 17.9 | +62 / +96 / +50 % | – | 1 / 1 |
| plain 600 m | 14.6 | 17.4 | +59 / +94 / +48 % | 12.7 / 27 | 1.009 / 0.996 |
| full rel 300 m | 0.63 | 0.57 | 0.1 / 1.8 / 0.2 % | 15.8 / 32 | 1.012 / 0.995 |
| full rel 600 m | 1.59 | 1.13 | −0.7 / 3.5 / 3.4 % | 15.3 / 29 | 1.009 / 0.994 |
| full rel 1000 m | 2.09 | 1.73 | −0.4 / 5.2 / 5.9 % | 15.3 / 27 | 1.009 / 0.995 |
| abs 600 m | 2.03 | 1.78 | −0.8 / 3.6 / **14.4** % | 40.8 / 75 | 0.940 / 0.993 |
| **feather σ_f 1500 m** | **0.77** | **0.56** | **0.2 / 1.7 / 0.2 %** | 9.7 / 24 | 1.005 / 0.996 |
| feather σ_f 600 m | 0.55 | 0.56 | 0.2 / 1.7 / 0.2 % | 4.1 / 22 | 1.001 / 0.997 |
| feather σ_f 3000 m | 0.77 | 0.56 | 0.2 / 1.7 / 0.2 % | 13.8 / 24 | 1.006 / 0.994 |
| feather 1500 m with S2 **2016** | 0.64 | 0.77 | 3.1 / 4.1 / 1.1 % | 0.8 levels mean from the 2023 result | |

Natural difference (S2): ΔE 0.58 at 200 m and 0.47 at 20 m. The feather removes the seam to within about 0.1–0.3 ΔE of that natural difference.

Row profile across the seam, log luminance, rows 2294–2306 averaged over 2000 columns:
- before: −1.08 → −1.70 within 3 px;
- after: −1.381 … −1.405, monotone, with no line.

The "abs" variant hits the B-channel clamp (S2 needs ×0.19 in B), so it keeps 10–14 % of the step in B.

Plain HF energy ratio in sRGB (texture contrast, not the log ratio):

| Variant | Ratio |
|---|---|
| feather | 1.026 |
| full rel | 1.054 |
| abs | 0.825 (darker image) |

**Feather σ_f.** The seam removal is the same for 600–3000 m; σ_f only sets how gently the half-steps fade. A 0.3 log half-step over 600 m is a visible gradient from the ground; 1500 m is not. Recommended: 1500 m.

### Far-field consistency

ΔE of 500 m means against S2 2023:

| Variant | vs S2 2023 |
|---|---|
| before | 37.5 |
| feather | 36.6 |
| full rel | 36.2 (but 3.1 against "S2 scaled into USGS' palette") |
| abs | 2.7 |

EOX S2 here is far more saturated and orange than NAIP. Matching the near field to it ("abs") changes every pixel by about 41 levels. Where the far rings switch from USGS (z ≥ 10) to EOX, that is a separate problem, and it needs a regional palette mapping (z10–z12 statistics), not a per-pixel match. Seam removal does not need S2's palette at all.

### Controls

Central Valley (farmland) and Baltimore (city):

| Variant | Seam cells detected | Mean / p99 change (levels) |
|---|---|---|
| feather | 0 / 0 | **0.00 / 0** in both (no-op) |
| full rel 600 m | – | 6.0 / 26 (CV), 9.0 / 37 (Balt.) |
| abs | – | 21 / 55 (CV), 45 / 78 (Balt.) |

Full rel repaints fields to S2's crop year and shifts city blocks. That counts as damage where there is no seam, which is why the feather is proposed. Figures: `colormatch_control_cvalley.png`, `colormatch_control_baltimore.png`.

### Synthetic seams (detection limits)

A slanted flight boundary with a 2 px blend was injected into real windows. Found = the fraction of the line detected. Residual = the R/G/B step after correction, 20 m bands.

| Injected step | Desert (UT half of the seam window) | Farmland | City |
|---|---|---|---|
| +10 / +7 / 0 % | not found (no change) | not found, 0 false cells | not found, 0 false cells |
| +18 / +12 / 0 % | 43 % found, residual 5 / 5 / 1 % | not found | not found |
| +35 / +25 / +10 % | 73 % found, residual 7 / 11 / 11 % | not found | not found |

The detector is conservative: zero false seams in all control runs. It does reliably catch large, km-long seams in homogeneous terrain, and those are the ones users see as "a border that stretches for miles".

In farmland and cities the USGS/S2 ratio has field-sized steps of ±0.3 from year-to-year land-cover change, and moderate seams are buried in them. An earlier, looser version (60 % segment agreement, or base weights) found 900–2300 false "seam" cells along crop-change fields in the Central Valley.

Partially found seams get partially corrected: the cut leaks through gaps.

Figures: `colormatch_synthetic_desert_18pct.png`, `colormatch_synthetic_farmland_35pct.png`.

### Timing (this machine, numpy, single thread)

**Region pre-computation** (7.8 × 7.8 km):

| Step | Time |
|---|---|
| detection (36 angles, 15 m grid) | 18–25 s |
| robust pre-blur | 1.1 s |
| cut blurs | 4 s |
| seam lines | 0.5 s |
| tile-ready arrays | 0.3 s |

Detection on the 7.6 m grid with 24 angles took 35 s. The detector was not optimised. Options:
- a 30 m detection grid (about 4× cheaper);
- prefiltering candidate cells by the L-gradient;
- a known-boundary prior (§5).

Seams are static per USGS imagery version, so all of this is computed once and cached on disk.

**Per 256 px tile** (`tile.py`; tile pipeline = 66 × 66 gain slice → phase-sliced bilinear ×4 → linear LUT → ×gain → 16-bit LUT):

| Tile kind | Median | Max |
|---|---|---|
| tile with no seam within reach | 0 ms (returned unchanged; every tile of both controls) | |
| smooth-gain tile | 1.2 ms | 1.9 ms |
| seam-band tile (side assignment + strip inpaint) | 1.9 ms | 2.2 ms |

All are under the 10 ms target. The tile output matches the full-window result within 1 level. The exception is the inpainted strip within 3 px of a tile edge, where the tile path clamped samples; in the server, `_mosaic` has the neighbour tiles.

`np.einsum` and BLAS for the ×4 upsample cost 7–15 ms. Phase slicing is used instead.

## 5. Failure cases and limits

- **Moderate seams in farmland and cities are not detected** (above). The best next step is a geometric prior: test steps only along known candidate lines.
  - Candidates are state boundaries, where NAIP years differ, as here, plus the NAIP DOQQ 3.75′ graticule and USGS mosaic seamlines if obtainable.
  - Along a known line, a 5 % step can be measured robustly over tens of km with no false positives.
- **Seams that coincide with a natural edge** (river, field edge, shoreline): the S2 gate rejects them, and the seam is left as is.
- **Snow or season**: NAIP is leaf-on summer, but flights in different years differ in greenness.
  - Feather measures the step locally from S2-normalised sides, so a seasonal difference across the line is corrected like any flight difference.
  - If S2 itself has a compositing seam (an EOX mosaic boundary or a 2023/2016 fallback edge), the step is in S2 only. The gate rejects it, and it is never imported into USGS.
  - Snow in one source gets weight 0.02.
- **Clouds and haze in S2**: the dark blotches in EOX 2023 west of the window (cloud shadows or compositing) were rejected by the robust weights and the gate. With S2 2016 the result changes by 0.8 levels on average.
- **Water**: near-zero weight, so a seam crossing a lake takes the gain from the shore cells. Specular glint differences are not modelled.
- **Cities**: lean and shadows make L noisy. Nothing is detected, and nothing changes.
- **Seam ends and T-junctions**: the half-steps are extended along each side and faded with distance. The correction stays approximately right up to a seam's end, then fades out over σ_f.
- **Residual 1–2 px features**: the mosaic's blend row is inpainted. JPEG ringing 5–8 px from the seam (a faint orange row in the source) is left.
- **Region borders**: detection needs at least 3 of 5 segments, so regions need a halo of at least 1 km. The feather needs neighbouring regions' seams within about 3 σ_f (4.5 km).

## 6. Interaction with de-shadowing

**Order per tile: raw → de-shadow → colour gain → tone LUT.** Seam analysis runs on the raw imagery, first.

- De-shadow's model (`I = A(amb + sun·lam·lit) + haze`) needs the source radiometry:
  - haze from the 0.5th percentile;
  - shadow/sun ratios measured in the image.

  Applying a colour gain first would change these per flight.
- The colour statistics should not use the de-shadowed tile:
  - cast shadows are already outliers with ~0 weight in the robust ratio (shadows differ between NAIP and S2 anyway, since S2 passes at about 10:30 local time);
  - waiting for de-shadow (sun fit 4 s per region) would serialise the two pre-computations.

  A gain computed from raw sunlit cells is the right gain for the de-shadowed tile, because de-shadow makes shadowed cells sunlit-equivalent.
- Both corrections are multiplicative in linear light (apart from de-shadow's haze term), so applying them in sequence is consistent.
- **De-shadow should consume the seam polylines.** Two flights mean two suns and two haze levels. The de-shadow report already lists "mosaic seams between flights" as a failure case, so it should fit the sun and haze per flight segment, splitting its z12 region at the detected seams.
- With `--deshadow full`, keep that branch's tone reduction; it is independent.

## 7. Integration plan (`server/imagery.py`, flag `--colormatch off|s2`, default off)

Status: integrated offline (`server/colormatch.py`, `server/tests/test_colormatch.py`); what was built,
the measured numbers and the deviations are in docs/ARCHITECTURE.md, "Colour seams of the USGS imagery".
Review correction to §5: the S2 gate alone does not reject a step in S2 only (|D_s2| ≈ |D| passes it
with a third of the score), so the edge of the per-tile 2016 fallback and EOX compositing steps were
imported into USGS; the integration now also requires USGS to carry each component's step.

- **New module `server/colormatch.py`.** Port `colormatch.py` and the `Region` and `apply` code from `tile.py`. Pure numpy.
- **Region unit: a USGS z12 tile.** About 7.8 km at 37° N, 1024² cells at z14.
  - Inputs:
    - USGS **z14** tiles (16 + a halo ring = 36; not z16 — the analysis grid is z14);
    - EOX 2023 z14 (fallback 2016 per tile).

    Both are fetched through the existing `Imagery.tiles()` (same cache, same UA, coverage probes).
  - Process a 3 × 3 block of z12 regions' cells for seam detection, or detect per region with a 1.5 km halo and merge polylines. Then compute the feather field for the centre region.
  - Background pool with 1 worker; prefetch triggers it.
- **Disk cache** `<cache>/colormatch/v1/usgs/12/<x>/<y>.npz`, versioned by the algorithm and the source chain:
  - seam cells with q, n and the per-side gains (band arrays, band widened to 8 cells);
  - the log-gain field at 30 m (float16, about 400 KB), or nothing when there is no seam (the common case: store an empty marker).
- **Hook.** In `Imagery._mosaic`, after `self.tiles(...)`, for `src.name == "usgs"` and z ≥ 12:

  ```python
  rgb = self.cm.apply(z, x, y, rgb, neighbours)   # neighbours for the 3 px strip inpaint
  ```

  - Corrected tiles go in a second LRU keyed `(src, z, x, y, "cm1")`. The raw `Tile` stays in `_lru`, so uniform and coverage-probe logic is untouched.
  - z14–16: as prototyped (z15 and z16 slice and upsample the z14-cell gain ×2 or ×4; the band and inpaint apply at z16 and z15).
  - z12–13: box-downsampled gain only.
  - z10–11 (far rings): use the same pipeline on z12 data (30 m cells, parameters scaled). This is still to be validated, because a state-line seam is visible on the horizon too.
- **Region not ready** (first visit): render raw, and remember the tile keys built raw for that region. When the region finishes, requeue those visual tiles for a texture rebuild (the same mechanism the de-shadow plan needs).
  - Status (2026-10-11, feature/cm-retex): done, live, for colour-match and de-shadow regions: the tiles a mod shows are re-rendered under a new file name and swapped in the game with `far_retex` (nearest first, `--retex-rate` 5/s, one render at a time; the mod switches the material's `colorMap` time-sliced). Before, the corrected look appeared only when a tile was sent again (a teleport). A tile is re-rendered once per region of it that turns ready (an L5/L6 texture spans up to 9/16 regions); a failed region reads as not ready. See docs/ARCHITECTURE.md, "Live retexture". Not yet checked in-game.
  - Alternatively, wait up to about 200 ms in `render` before falling back (not done).
  - Log once per region: seams found (count, length, step %), time, cache hit.
- **CLI.** `--colormatch off|s2` in `earthd.py`, passed into `Imagery(..., colormatch=...)`. `off` must be byte-identical to today.
  - `s2` = seam feather (σ_s 300 m, σ_f 1500 m, split 0.5, clamp ±log 2).
  - Do not ship the "full rel" or "abs" modes.
  - Attribution is unchanged: S2 is only used as a reference, but EOX is already credited.
- **Tests** (`server/tests/test_colormatch.py`, offline, synthetic):
  1. `dt_blur` keeps constants, and an impulse on one side of a cut gives exactly 0 on the other side.
  2. `detect_seams`: a synthetic step + noise at 0–165° finds the normal within 5° with score ≈ |step|. Pure noise → no seam. A 600 m square patch present in USGS only (crop change) → rejected by the length and consistency filter.
  3. `seam_lines`: an image with a 2 px blended step at a fractional row gives the line within 0.3 px.
  4. Feather end-to-end on textured noise × a +40 % gain step with a flat S2: residual step < 2 % (20 m bands), gain == 1 beyond 4 σ_f, log-HF ratio within 1 %, clamp respected.
  5. `Region.apply` per tile == full-window result within 1 level, with neighbour margins.
  6. No-seam region: `apply` returns the input unchanged (identity, 0 ms path).
  7. `--colormatch off`: `render` output byte-identical to the current code (regression against a fixture).
  8. Cache round-trip and version invalidation.
  9. A loose performance guard: < 10 ms per tile.
  10. Optionally, a `fake_imagery_earthd.py` variant with an injected seam for the drive test.
- **Before default-on:** add the state-boundary/graticule prior (§5), and check a handful of known state-line seams (UT/AZ, NM/CO, KS/NE) plus mountain snow regions in-game.

## 8. Files

`docs/research/imagery_seams/`:

| File | Contents |
|---|---|
| `colormatch_seam_window.png` | before, plain 600 m, **feather 1500 m**, full rel 600 m, abs, S2 2023 |
| `colormatch_seam_zoom.png` | 490 m (256 px) crop at the user's point, ×2 |
| `colormatch_seam_detect.png` | detected seam over USGS, and the score map |
| `colormatch_sigma_sweep.png` | feather 600 / 1500 / 3000, full rel 300 / 1000, plain 1000 |
| `colormatch_control_cvalley.png`, `colormatch_control_baltimore.png` | before, feather, its diff ×4, full rel, its diff ×4, S2 |
| `colormatch_synthetic_desert_18pct.png`, `colormatch_synthetic_farmland_35pct.png` | synthetic seams |

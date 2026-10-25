# How far can BeamNG render? (in-game probe, 2026-10-10)

Setup: free camera 10 km above Baltimore, looking north (fov 65); a 131 km wide flat marker (our L7
far-tile shape scaled 4x) placed at 50 ... 6400 km; screenshots diffed against a marker-hidden shot.
Tools: tools/probe_view_distance.py, tools/probe_view_distance_each.py. Screenshots in
docs/research/view_distance/ (not in git).

| visibleDistance set to | how | markers rendered |
|---|---|---|
| 100 / 1000 / 20000 km | field assigned only | 50, 100 km (200 km barely); nothing beyond |
| same, fog density 0 | field assigned only | same: fog is not the limit |
| 1000 km | field + `LevelInfo:postApply()` | 50 ... 800 km |
| 20000 km | field + `postApply()` | 50 ... 3200 km (tiny at 3200), none at 6400 |

Findings:
- Assigning `scenetree.theLevelInfo.visibleDistance` at runtime is ignored until `postApply()`; the
  engine keeps the level file's value (ours: 100 km). The mod's own runtime assignment was a no-op.
- With postApply the engine draws objects thousands of km away; markers at 400 and 800 km render as
  clean shapes tinted by the sky's aerial perspective, no depth artefacts seen.
- Frame cost of the setting alone (no extra geometry) was within ~1 ms in the earlier P12 runs; the
  cost of real distant tiles is measured with M1h.
Consequences: M1h calls postApply after each change and caps the far field at 1500 km (eyes up to
~40 km altitude); docs/V1_4_SPEC.md M1h.

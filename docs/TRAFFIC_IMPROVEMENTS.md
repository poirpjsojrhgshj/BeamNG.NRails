# Roundabouts, narrow streets and curved AI routes

The streamed road graph now retains tighter curves on narrow streets, keeps recognised roundabout rings
one-way, and gives incoming traffic lower priority than circulating traffic. The changes use geometry,
road attributes and the existing driving-side setting, without location-specific rules.

## Behaviour

- Recognised rings inherit their mapped circulation. Where a direction is missing, it follows the other
  mapped arcs, or the driving side if the whole ring is unmapped. Mainland-style traffic circulates
  counter-clockwise; left-hand traffic circulates clockwise. Explicit mapped directions take precedence.
- Incoming external arms have give-way signs, including at rural roundabouts. The stock AI's edge
  drivability comparison gives the ring priority. No stop-sign controller or traffic light is installed
  on the ring, and no unsupported yield signal action is used.
- Roundabout rings and their immediate entry edges have a maximum driving target of 30 km/h, reduced
  further by tighter curvature or a lower mapped limit.
- Curve simplification uses a width-dependent tolerance of 0.1 to 0.6 m, and shorter graph edges on narrow
  roads. Finite-chord distances retain hairpin reversals that the old infinite-line calculation erased.
- Driving targets account for curvature using 2 m/s2 lateral acceleration and spread reductions along
  each road with 2.5 m/s2 braking. Two-way carriageways under 5.5 m have a 30 km/h target cap. These are
  driving targets, not new legal limits: mapped limits and the road-sign values remain authoritative.
- Speed-limit changes within a source segment now have separate graph edges. Long roads crossing the
  graph window remain present even when both original endpoints are outside it.
- Reliable building-to-building measurements can produce local carriageways as narrow as 3 m, with
  narrower sidewalks where necessary. The carriageway and sidewalks fit within the measured width.
  Existing measurement-confidence checks and upper width bounds remain in place.

## Validation on Windows, 2026-10-19

142 Python tests passed across the traffic graph, roundabout detection, street furniture, widths,
road generation, grading, junctions, sidewalks, parking, road meshes and surfaces. The new scenarios
cover mixed geometry directions, mainland and left-hand circulation, mapped direction precedence,
ring priority, rural give-way signs, through-road rejection, narrow building gaps, S-bends, hairpins,
braking profiles, unchanged straight motorway limits and speed-limit transitions.

The builder was also exercised offline on 12 cached source cells around Les Sables-d'Olonne, France,
using cached land cover and building measurements. That sample produced 6,269 nodes and 6,537 edges,
compared with 4,601 nodes and 4,871 edges using the previous graph builder on the same source inputs.
The extra curve detail has a node/memory cost; this is not a claim of improved frame rate.

A temporary candidate graph was loaded into the running BeamNG.Earth level through the game's MCP
server. New nodes used heights interpolated from the active server's original graded/deck graph,
so the existing world's physics and rendering were retained. The engine accepted a clipped graph
of 1,179 nodes and 1,218 edges. Three stock traffic vehicles were observed over ten samples for about
30 seconds; recorded movement was approximately 165, 251 and 156 m. The changed Lua module compiled
in the game and its give-way sign resolved to an existing stock asset. The original graph and the
initial traffic-off state were restored, keeping the original player vehicle.

This is a runtime smoke test of the generated graph, not an end-to-end validation of a rebuilt world,
every roundabout, collision-free driving or long-session performance. Ring recognition remains a
geometric heuristic, and close encounters on shared narrow lanes still use BeamNG's stock AI.
Longer multi-vehicle roundabout, UK, steep-street and dense-city tests remain necessary.

Additional protocol checks found two existing failures in `AgreementTableTest`: the protocol test table
does not include the existing `open_page` message and its `url` field. Both failures reproduce using
the unmodified upstream `core.lua` and `earthd.py`; neither file is changed by this contribution.
The protocol suite finished with 29 passes, these 2 failures and 1 skip because standalone LuaJIT
was not installed. The source environment's `pip check` and `server/earthd.py --help` also passed.

## Run the source version

Use the normal source-install workflow in [QUICKSTART.md](QUICKSTART.md). Stop any running companion
server before starting another one on the same port. Run `install.py` with a compatible Python,
then `run_server.bat` on Windows or `run_server.sh` on Linux. Reload the BeamNG.Earth level after
updating the mod so new street-furniture groups are loaded. A packaged executable from an earlier
release keeps its bundled server and does not automatically use this checkout's changes.

For the targeted Python checks, run from the repository root:

```text
python -m unittest discover -s server/tests -p test_european_traffic.py -v
```

The stock engine behaviour used for priority is documented in
[the existing navgraph research](research/2026-10-10-navgraph-traffic-signals.md), section 4.4,
and was checked against the installed game's `lua/vehicle/ai.lua` during this change.

# BeamNG.NRails — release notes

## 1.1.0 — for BeamNG.Earth 1.6.3-beta

**Works with BeamNG.Earth 1.6.3-beta** (included: this download is BeamNG.Earth 1.6.3-beta + NRails). Everything
below is new since 1.0.0-beta.

### BeamNG.Earth 1.6.3
- Now based on **BeamNG.Earth 1.6.3-beta**, with all of its new things: places you have been load much faster the
  next time, gas stations, traffic lights and sidewalks where the map has them, GPS routes downloaded ahead,
  European speed limit signs, smoother junctions, short teleports as quick as long ones, and more. The map's road
  data downloads again once after the update (the first place you visit takes a few minutes).
- BeamNG.Earth 1.6.3 has railway track of its own. NRails keeps its own and switches BeamNG.Earth's off while
  NRails' rails are on (two tracks one in the other otherwise, and the ground graded twice). Turn NRails' rails off
  in the Hub and you get BeamNG.Earth's railways instead.

### Turnouts
- **Reworked from A to Z.** Each turnout knows the track it comes from, its routes and its main route (the busiest
  line first, then the straightest). Only the set route is solid; ladders, crossovers and diamonds are handled;
  every train sets a turnout it runs through from a branch; a turnout with a vehicle on it never changes.
- **A track joining yours no longer hits your train**: the other route's rails stay out of the collision until they
  are clear of the train's body (bogies, snowplows), not only of its wheels.
  A train arriving on a branch sets its turnout even when it is already in it (a turnout whose part of the map
  came late stayed on the other route before).
- **Track diagram** (Ctrl+Shift+M, shown until you press it again, stopped too): the tracks and turnouts round your
  train, the set routes green, your choices yellow, your itinerary blue.
  - **Click a branch** to set that turnout (as soon as no train is on it): several turnouts can be set ahead.
  - **Click a track** for an **itinerary**: the way there along the rails (never reversing) is found and every
    turnout on it set for you.
  - Buttons: area / turnout view, zoom, clear.
- **Light signals** 40 m before the turnouts: green (main line), yellow (diverging route), red (a vehicle on the
  turnout). Hub setting to turn them off.
- Keys still work: Ctrl+Shift+← / ↑ / → for the next turnout ahead.

### Driving
- **Keys window** when you board a train (with *do not show again*); Ctrl+Shift+I shows it any time.
- **Snap to rail** pressed again within 6 s: the next track beside.
- **Coupling** (Ctrl+Shift+O / Ctrl+Shift+N, buttons in the keys window): coupling is armed for 60 s on your vehicle
  and the rail vehicles within 80 m; drive gently until the couplers are within 2 m (the rail mods' coupler reach):
  the status line shows the gap. Works whichever way the vehicles meet (two ends with the same coupler type, e.g. two
  locomotives nose to nose, never coupled with the game's own auto-coupling).
- **Level crossings**: the slabs follow the track (curves and grades) and stop short of the other tracks: the WLD
  FS30-2's snowplow passes. No ghost collision when a train comes near.
- No cant through turnouts (the set route was twisted).
- A train waits for the finished ground after a teleport (the terrain came back over the rails).

### World
- **Fixed: tracks, roads and bridges missing** near stations: a road tile with a road bridge over a track failed as a
  whole, and a tile's rails were lost when a viaduct's piers were placed.
- **Fixed: +20 GB of RAM** a minute into a map (the turnout search): under 1 GB now.
- Roads under rail bridges: no lumps of ballast on them any more. Viaduct piers no longer stand on a road or another
  track under them.
- Short "tunnels" under road bridges are open track; abandoned lines are left out (disused ones stay); bits of track
  under 50 m on their own are left out.
- Faster: one scan of the vehicles for turnouts, crossings and signals; turnouts found once per tile; the places
  cache of BeamNG.Earth 1.6.3 knows NRails (a new version or other rail settings rebuild the tracks).
- Hub: BeamNG.NRails and its version beside BeamNG.Earth's.

## 1.0.0-beta — first public version

Based on BeamNG.Earth 1.6.2-beta.

**Track**
- Real rail network (Overture Maps `rail` segments: standard gauge, light rail, narrow gauge; trams drawn only;
  abandoned / disused lines left out) built as drivable track next to the roads, in the same streamed tiles.
- UIC 60 / UIC 54 / UIC 50 / JIS 60 rail profiles, B70-type sleepers, ballast, cant in curves.
- One profile per map cell shared by every tile (no steps at tile seams), grade cap, embankments and cuttings,
  a corridor cut into the terrain around the track.
- Viaducts (slab, parapets, piers), tunnels (straight portal to portal, tubes, mouths cut, undersea tunnels dived
  under the sea floor), catenary.
- Level crossings (slabs, flangeways, solid for cars only while no train is near), grade-separated crossings kept
  at their own level.
- Road bridges over the track: 6 m free, thin slab decks where too low, piers kept off the tracks; street
  furniture, wires and retaining walls kept off the track.
- Stations: platforms at track level, footbridges and halls lifted over the tracks.
- Turnouts: per-route collision, only the set route solid; set from the train (Ctrl+Shift+arrows) or by the train
  when taken from a branch; no cant through a turnout's zone (eased out over 25 m before it).
- Level crossing slabs follow the track's curve and grade (never over the rail top: low snowplows pass).

**Game side**
- Snap to rail (Ctrl+Shift+T), Reload area (Ctrl+Shift+G), the window (Ctrl+Shift+U), the keys' help
  (Ctrl+Shift+I / *Keys* button).
- Loading guard: the game held while the track ahead is not loaded; teleports ignored by it.
- Far trains keep a collision island; no water physics inside undersea tunnels.

**Hub**
- Install / update, server, game launch, rails settings, cache folder and clean-up, switch back to BeamNG.Earth.

**Known limits**: see the README.

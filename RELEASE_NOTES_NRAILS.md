# BeamNG.NRails — release notes

## 1.0.1-beta — bug fixes

- **Level crossings: the WLD FS30-2 passes.** The crossing slabs were a straight strip at the rail top of the
  crossing's centre: on a curve or a grade their ends stood up to ~0.2 m over the rails, in the way of a WLD
  FS30-2's snowplow (0.13 m over the rail top). They now follow the track, its curve and grade, never over the rails.
- **Level crossings and turnouts: no ghost collision.** When a train came near, the crossing's solid inner slab
  (or a turnout's other route) was replaced by a drawn-only one, but the old one's collision could stay up to 30 s
  (its deletion counted as "far away", waiting for a lazy collision rebuild): the train hit a slab it could not see.
  It is now deleted at once and the collision rebuilt within about a second; a fast train opens the crossings 15 s
  ahead of it (at least 150 m).
- **Turnouts on canted track.** A turnout's diverging route got its own cant while the straight one had none: the
  set route's rails were twisted and a bogie could not take it. No cant through a turnout any more (none within 25 m
  of its zone, eased back in over 25 m), as on real track.
- Names: "NRails" / "BeamNG.NRails" everywhere in the project's own files (the Hub, the key names, the docs).

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

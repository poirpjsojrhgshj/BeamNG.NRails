# BeamNG.NRails — release notes

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
  when taken from a branch.

**Game side**
- Snap to rail (Ctrl+Shift+T), Reload area (Ctrl+Shift+G), the window (Ctrl+Shift+U), the keys' help
  (Ctrl+Shift+I / *Keys* button).
- Loading guard: the game held while the track ahead is not loaded; teleports ignored by it.
- Far trains keep a collision island; no water physics inside undersea tunnels.

**Hub**
- Install / update, server, game launch, rails settings, cache folder and clean-up, switch back to BeamNG.Earth.

**Known limits**: see the README.

# Winter / seasons reference notes (2026-10-10)

Source: MuYe, "They Added Seasons To BeamNG" (YouTube, 2026-09-13, https://www.youtube.com/watch?v=-Ga0a2fmmJo),
about the "Polish Roads" map by mcct (https://www.beamng.com/resources/polish-roads.5846/, summer +
winter versions). Paraphrased notes only (transcript kept out of the repo). Polish Roads' assets may
not be reused; it is a visual reference.

What makes the winter version convincing:
- Everything changes with the season: snow on objects, bare trees, frozen water, lower temperature
  (visible as exhaust steam).
- Snow follows traffic: busy city roads look driven-on and recently plowed (icy but drivable on summer
  tyres); less-used spots (a bus stop) keep more snow; quiet country roads are fully covered.
- Snow banks are dirty at the bottom and get cleaner toward the top.
- Ice patches are slipperier than the surrounding asphalt.
- Night: lit building windows.

The video's reasons the official game has no seasons (constraints for us too):
1. "How much snow?" (first snow, heavy, old, plowed, untouched, icy, mixed by traffic) - real data
   answers this for us: use the real snow of the day and plow by road class.
2. No winter / all-season / studded tyres, and the tyre physics is being reworked by BeamNG.
3. No terrain deformation for deep snow, mud or sand (no ruts or tracks; cars sink through deep snow).
4. Snow banks and ruts should depend on vehicle mass (a wall for a light car, minor for a truck);
   neither solid meshes nor ghost meshes are right.
5. Snow build-up on tyres would need variable tyre physics and visuals.
6. Season approaches: standalone winter map / four versions per map / dynamic seasons (called nearly
   impossible). For BeamNG.Earth dynamic seasons come naturally: the world is generated at runtime
   from the real date and data.

Consequences for the roadmap (seasons section): snow by traffic level (road class, later traffic
data), dirty-to-clean snow-bank material gradient, low/soft snow banks rather than solid walls,
ice patches (refrozen melt, shade) with the ICE ground model, frozen lakes from the temperature
history, lit windows at night (v1.9), sensible SNOW/ICE friction since winter tyres do not exist;
deformation and winter tyres depend on BeamNG.

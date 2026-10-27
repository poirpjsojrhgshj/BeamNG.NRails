// BeamNG.NRails: what the map's NRails parts share (NRailsMapTab / NRailsMapLayer / NRailsMapMenu, hooked into
// EarthMap.vue): the railway layer on / off (remembered in this browser), the lines in view, the itinerary.
import { reactive } from "vue"

function stored(k, d) { try { const v = window.localStorage.getItem(k); return v == null ? d : v } catch (e) { return d } }
function store(k, v) { try { window.localStorage.setItem(k, v) } catch (e) { /* (no storage: per session) */ } }

export const nrailsMap = reactive({
  on: stored("nrails.map.rails", "1") !== "0",
  rails: [],          // the loaded tracks: [[lat, lon, lat, lon, ...], ...]
  osm: [],            // OpenStreetMap's railways: [{k, p: [lat, lon, ...]}, ...]
  itin: null,         // { pts: [[lat, lon], ...], length, turnouts }
  route: null,        // the route along OSM: { pts, dist }
  far: null,          // { lat, lon }
  osmState: null,     // { asked, done, total, n, reach, error }
  asking: false,
  mpp: 10,            // m a pixel at the view's zoom
  msg: "",
})

export function setOn(v) {
  nrailsMap.on = !!v
  store("nrails.map.rails", v ? "1" : "0")
}

// A Lua table as it comes through engineLua: an array, or an object keyed "1", "2", ...
export function arr(t) {
  if (!t) return []
  if (Array.isArray(t)) return t
  const out = []
  for (let i = 1; t[i] !== undefined || t[String(i)] !== undefined; i++) out.push(t[i] !== undefined ? t[i] : t[String(i)])
  return out
}

export const LUA = "beamngEarth_core and beamngEarth_core.nrails and beamngEarth_core.nrails.map"

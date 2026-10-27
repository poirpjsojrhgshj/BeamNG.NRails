<template>
  <!-- BeamNG.NRails: OpenStreetMap's railways round the player (reachable from its track), the loaded tracks, the
       train's itinerary and its route along OSM drawn on BeamNG.Earth's map (an svg group) -->
  <g v-if="nrailsMap.on" class="nrails-layer">
    <polyline v-for="(p, i) in osm" :key="'o' + i" :class="'nrails-osm nrails-osm-' + p.k" :points="p.s" />
    <polyline v-for="(p, i) in lines" :key="'r' + i" class="nrails-track-casing" :points="p" />
    <polyline v-for="(p, i) in lines" :key="'t' + i" class="nrails-track" :points="p" />
    <polyline v-if="route" class="nrails-route" :points="route" />
    <polyline v-if="itin" class="nrails-itin" :points="itin" />
    <circle v-if="far" :cx="far.x" :cy="far.y" r="7" class="nrails-far" />
  </g>
</template>

<script setup>
import { computed, onMounted, onUnmounted, watch } from "vue"
import * as mm from "./mapmath.js"
import { nrailsMap, arr, LUA } from "./nrailsMapStore.js"

const props = defineProps({
  view: Object, w: Number, h: Number,
  screen: Function,       // (lat, lon) -> {x, y}: EarthMap's
  engineLua: Function,
})

const MIN_Z = 11            // (the loaded tracks span a few km: not drawn when zoomed further out)
const OSM_MIN_Z = 6

function pts(list) { return arr(list).map(p => arr(p).map(Number)) }

function ask() {
  if (!nrailsMap.on || !props.engineLua || !props.view) return
  const v = props.view
  const a = mm.fromScreen(0, 0, v.lat, v.lon, v.z, props.w, props.h)
  const b = mm.fromScreen(props.w, props.h, v.lat, v.lon, v.z, props.w, props.h)
  const mpp = 156543.03 * Math.cos(v.lat * Math.PI / 180) / Math.pow(2, v.z)
  nrailsMap.mpp = mpp
  const step = Math.max(2, Math.min(60, 3 * mpp))
  const lat0 = Math.min(a.lat, b.lat), lat1 = Math.max(a.lat, b.lat)
  const lon0 = Math.min(a.lon, b.lon), lon1 = Math.max(a.lon, b.lon)
  if (v.z < MIN_Z) nrailsMap.rails = []
  else props.engineLua(`${LUA} and ${LUA}.rails(${lat0}, ${lon0}, ${lat1}, ${lon1}, ${step.toFixed(1)}) or {}`, r => {
    nrailsMap.rails = arr(r).map(l => arr(l).map(Number))
  })
  if (v.z < OSM_MIN_Z) nrailsMap.osm = []
  else props.engineLua(`${LUA} and ${LUA}.osmLines(${lat0}, ${lon0}, ${lat1}, ${lon1}, ${Math.floor(v.z)}) or {}`, r => {
    nrailsMap.osm = arr(r).map(l => ({ k: String(l.k || "branch"), p: arr(l.p).map(Number) }))
  })
  props.engineLua(`${LUA} and ${LUA}.state() or nil`, s => {
    nrailsMap.itin = s && s.itin ? { ...s.itin, pts: pts(s.itin.pts) } : null
    nrailsMap.route = s && s.route ? { dist: Number(s.route.dist), pts: pts(s.route.pts) } : null
    nrailsMap.far = s && s.far ? { lat: Number(s.far.lat), lon: Number(s.far.lon) } : null
    nrailsMap.osmState = s && s.osm ? s.osm : null
    nrailsMap.asking = !!(s && s.asking)
  })
}

function toPts(l) {
  const out = []
  for (let i = 0; i + 1 < l.length; i += 2) {
    const s = props.screen(l[i], l[i + 1])
    out.push(`${s.x.toFixed(1)},${s.y.toFixed(1)}`)
  }
  return out.join(" ")
}
const lines = computed(() => { props.view; props.w; props.h; return nrailsMap.rails.map(toPts) })
const osm = computed(() => { props.view; props.w; props.h; return nrailsMap.osm.map(l => ({ k: l.k, s: toPts(l.p) })) })
function line(list) {
  if (!list || list.length < 2) return ""
  return list.map(p => { const s = props.screen(p[0], p[1]); return `${s.x.toFixed(1)},${s.y.toFixed(1)}` }).join(" ")
}
const itin = computed(() => { props.view; props.w; props.h; return line(nrailsMap.itin && nrailsMap.itin.pts) })
const route = computed(() => { props.view; props.w; props.h; return line(nrailsMap.route && nrailsMap.route.pts) })
const far = computed(() => {
  props.view
  return nrailsMap.far ? props.screen(nrailsMap.far.lat, nrailsMap.far.lon) : null
})

let timer = null, soon = null
watch(() => [props.view, props.w, props.h, nrailsMap.on], () => {
  clearTimeout(soon)
  soon = setTimeout(ask, 250)
})
onMounted(() => { ask(); timer = setInterval(ask, 2000) })
onUnmounted(() => { clearInterval(timer); clearTimeout(soon) })
</script>

<style scoped>
.nrails-osm { fill: none; stroke-linecap: round; stroke-linejoin: round; }
.nrails-osm-main { stroke: #c2410c; stroke-width: 2.6; }
.nrails-osm-branch { stroke: #ea7a2a; stroke-width: 1.8; }
.nrails-osm-light { stroke: #b45cd6; stroke-width: 1.5; }
.nrails-osm-service { stroke: #d9a066; stroke-width: 1.1; opacity: 0.85; }
.nrails-track-casing { fill: none; stroke: rgba(20, 20, 20, 0.85); stroke-width: 5; stroke-linecap: round; stroke-linejoin: round; }
.nrails-track { fill: none; stroke: #ff7a1a; stroke-width: 2.5; stroke-linecap: round; stroke-linejoin: round; }
.nrails-route { fill: none; stroke: #2f9bff; stroke-width: 4; opacity: 0.7; stroke-linecap: round; stroke-linejoin: round; }
.nrails-itin { fill: none; stroke: #2f9bff; stroke-width: 5; stroke-dasharray: 10 6; stroke-linecap: round; opacity: 0.95; }
.nrails-far { fill: rgba(47, 155, 255, 0.35); stroke: #2f9bff; stroke-width: 2; }
</style>

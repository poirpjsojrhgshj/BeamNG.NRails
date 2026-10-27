<template>
  <!-- BeamNG.NRails: the map's right-click menu, the railway part (an itinerary there, a teleport onto the track) -->
  <div class="nrails-menu">
    <div class="ctx-sub">Rails (NRails)</div>
    <template v-if="pick">
      <div class="ctx-item" @click="itinerary(pick.lat, pick.lon)">Itinéraire ferroviaire jusqu'ici
        <span class="nr-dim">({{ pick.loaded ? 'voie chargée' : 'OpenStreetMap' }}, à {{ Math.round(pick.d) }} m)</span></div>
      <div class="ctx-item" @click="teleport(pick.lat, pick.lon)">Téléporter sur la voie ici</div>
    </template>
    <template v-else>
      <div class="ctx-item" @click="itinerary(ctx.lat, ctx.lon)">Itinéraire vers la voie la plus proche d'ici</div>
      <div class="ctx-item" @click="teleport(ctx.lat, ctx.lon)">Téléporter ici puis mettre sur les rails</div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue"
import { nrailsMap, LUA } from "./nrailsMapStore.js"

const props = defineProps({ ctx: Object, engineLua: Function })
const emit = defineEmits(["close"])
const pick = ref(null)

onMounted(() => {
  if (!props.engineLua || !props.ctx) return
  const reach = Math.max(40, 14 * (nrailsMap.mpp || 10))   // (~14 px round the click)
  props.engineLua(`${LUA} and ${LUA}.pick(${props.ctx.lat}, ${props.ctx.lon}, ${reach.toFixed(0)}) or nil`, r => {
    pick.value = r && r.lat !== undefined
      ? { lat: Number(r.lat), lon: Number(r.lon), d: Number(r.d), loaded: !!r.loaded } : null
  })
})

function done(r) {
  nrailsMap.msg = r && r.msg ? String(r.msg) : ""
  emit("close")
}
function itinerary(lat, lon) {
  props.engineLua(`${LUA} and ${LUA}.itinerary(${lat}, ${lon}) or nil`, done)
}
function teleport(lat, lon) {
  props.engineLua(`${LUA} and ${LUA}.teleportRail(${lat}, ${lon}) or nil`, done)
}
</script>

<style scoped>
.ctx-sub { margin-top: 4px; padding: 4px 10px 2px; font-size: 11px; opacity: 0.7; border-top: 1px solid rgba(255, 255, 255, 0.15); }
.nr-dim { opacity: 0.65; font-size: 11px; }
</style>

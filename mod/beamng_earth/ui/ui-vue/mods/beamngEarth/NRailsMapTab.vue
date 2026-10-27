<template>
  <!-- BeamNG.NRails: the map's "Rails" button and panel (the railway layers, OSM's loading, the itinerary) -->
  <div class="layers-wrap nrails-tab" @mousedown.stop @wheel.stop @dblclick.stop>
    <button class="map-btn" :class="{ on: open }" @click="open = !open" title="Rails : voies ferrées et itinéraires (NRails)">Rails</button>
    <div v-if="open" class="layers-panel nrails-panel">
      <div class="panel-sub">BeamNG.NRails</div>
      <label class="layer-opt"><input type="checkbox" :checked="nrailsMap.on" @change="setOn($event.target.checked)" />
        Voies ferrées</label>
      <div class="nr-line nr-dim">
        <span class="nr-key nr-main"></span> OpenStreetMap, 100 km
        <span v-if="osm && osm.reach">accessibles depuis ta voie</span>
        <span class="nr-key nr-loaded"></span> chargées
      </div>
      <div class="nr-line nr-dim" v-if="osm">
        <template v-if="osm.total > 0 && osm.done < osm.total">chargement OSM {{ osm.done }}/{{ osm.total }}…</template>
        <template v-else-if="osm.asked && !osm.n">chargement OSM…</template>
        <template v-else-if="osm.n">{{ osm.n }} lignes OSM</template>
        <span v-if="osm.error" class="nr-err"> · {{ osm.error }}</span>
      </div>
      <button class="map-btn small" @click="refresh">Recharger OSM</button>
      <div class="panel-sub">Itinéraire</div>
      <div v-if="nrailsMap.asking" class="nr-line nr-dim">calcul…</div>
      <div v-if="nrailsMap.route" class="nr-line">{{ (nrailsMap.route.dist / 1000).toFixed(1) }} km le long des voies (OSM)</div>
      <div v-if="nrailsMap.itin" class="nr-line">
        réglé sur {{ (nrailsMap.itin.length / 1000).toFixed(1) }} km chargés, {{ nrailsMap.itin.turnouts }} aiguillage(s)
      </div>
      <div v-if="!nrailsMap.itin && !nrailsMap.route && !nrailsMap.asking" class="nr-line nr-dim">aucun</div>
      <button v-if="nrailsMap.itin || nrailsMap.far || nrailsMap.route" class="map-btn small" @click="clear">Effacer</button>
      <div class="nr-help">Clic droit sur une voie : itinéraire jusque-là (le long des voies, sans rebroussement ; les
        aiguillages se règlent seuls au fur et à mesure que les voies se chargent) ou téléportation sur la voie.</div>
      <div v-if="nrailsMap.msg" class="nr-line nr-dim">{{ nrailsMap.msg }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from "vue"
import { nrailsMap, setOn, LUA } from "./nrailsMapStore.js"

const props = defineProps({ engineLua: Function })
const open = ref(false)
const osm = computed(() => nrailsMap.osmState)
function clear() {
  if (props.engineLua) props.engineLua(`${LUA} and ${LUA}.clear() or nil`)
  nrailsMap.itin = null
  nrailsMap.route = null
  nrailsMap.far = null
}
function refresh() {
  if (props.engineLua) props.engineLua(`${LUA} and ${LUA}.refreshOsm() or nil`)
}
</script>

<style scoped>
.nrails-panel { min-width: 270px; }
.nr-line { padding: 3px 0; font-size: 12px; }
.nr-dim { opacity: 0.7; }
.nr-err { color: #ff8a7a; }
.nr-key { display: inline-block; width: 14px; height: 3px; vertical-align: middle; margin: 0 3px 0 6px; }
.nr-main { background: #c2410c; }
.nr-loaded { background: #ff7a1a; box-shadow: 0 0 0 1px #141414; }
.nr-help { margin-top: 6px; font-size: 11px; opacity: 0.75; line-height: 1.35; }
</style>

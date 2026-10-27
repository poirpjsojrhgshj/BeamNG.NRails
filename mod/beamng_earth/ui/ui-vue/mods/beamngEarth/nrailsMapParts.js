// BeamNG.NRails: the map's railway parts for EarthMap.vue (its NRails hook lines), loaded asynchronously: one that
// fails to load or compile renders nothing and logs, and BeamNG.Earth's map goes on as without NRails.
import { defineAsyncComponent } from "vue"

function part(name, load) {
  return defineAsyncComponent({
    loader: () => load().then(m => m.default).catch(e => {
      console.error("BeamNG.NRails: map part " + name + " failed", e)
      return { render: () => null }
    }),
  })
}

export const NRailsMapLayer = part("layer", () => import("./NRailsMapLayer.vue"))
export const NRailsMapMenu = part("menu", () => import("./NRailsMapMenu.vue"))
export const NRailsMapTab = part("tab", () => import("./NRailsMapTab.vue"))

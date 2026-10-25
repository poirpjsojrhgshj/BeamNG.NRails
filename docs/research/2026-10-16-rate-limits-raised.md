# Rate limits raised (2026-10-16)

The user asked to raise the per-host limits of docs/research/2026-10-10-rate-limits.md ("we can lower it again
if we run into issues"; every player runs their own server, so these are per player).

| Host | Before | Now |
|---|---|---|
| basemap.nationalmap.gov (USGS photos, CloudFront) | 15/s, burst 60, 6 at once, 60k/day | 50/s, burst 150, 12 at once, 150k/day |
| tiles.mapterhorn.com (elevation, Cloudflare) | 20/s, burst 80, 8 at once, 30k/day | 50/s, burst 200, 32 at once, 80k/day (a tile not in the edge cache: ~1 s to first byte) |
| tiles.maps.eox.at (photos outside the US, no CDN, throttles) | 6/s, burst 30, 4 at once, 20k/day | 10/s, burst 40, 6 at once, 30k/day |

Fetch threads to match: imagery.FETCH_WORKERS 6 -> 12, dem.Dem: 16 shared + 16 urgent (Dem.urgent) fetch threads.

Why: a first visit's far field (~500 tiles, ~1500 USGS requests) waited ~100-140 s on 15/s (Crater Lake, Mount
Hood). Watch for 429 / 503 / throttling redirects (netfetch's breakers log them) and lower a host again if it
pushes back.

## 2026-10-23: USGS raised again (the user: "sure raise the limit")

basemap.nationalmap.gov max_conc 12 -> 24, imagery FETCH_WORKERS 12 -> 16. Measured first (fresh caches, detail
mode, Helena MT, PC): 12 at once gave 26.2-27.1 requests/s and the far field in 68.3-68.8 s; 24 gave 24.7/s and 67.8 s;
every request answered 200. A Steam Deck's first visit (Richland WA, BNGE_NETLOG) made only 456 USGS requests at ~4/s:
its far field is paced by its CPU (the elevation fetches come in bursts as the workers reach them), not by USGS. The
higher cap is for players far from USGS, whose every request waits longer.

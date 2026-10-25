"""Fetch USGS z16 imagery + DEM for a window on the imagery's Web-Mercator pixel grid.
Uses server/imagery.py and server/dem.py unmodified (their caches, their generic UA)."""
import math, os, sys, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "server"))
import imagery as im
import dem as demmod

HOME = os.path.expanduser("~/.cache/beamng-earth")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def fetch(name, lat, lon, z=16, size_m=3000.0, dem_zoom=15, pad_m=1500.0, chain=("usgs",)):
    res = im.ground_res(lat, z)
    W = int(round(size_m / res / 2)) * 2
    cx, cy = im.mercator_px(lat, lon, z)
    x0, y0 = int(cx) - W // 2, int(cy) - W // 2
    tx0, ty0 = x0 // 256, y0 // 256
    tx1, ty1 = (x0 + W - 1) // 256, (y0 + W - 1) // 256
    I = im.Imagery(os.path.join(HOME, "imagery"), chain)
    src = I.chain[0]
    keys = [(src, z, tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)]
    t = time.time()
    got = I.tiles(keys)
    mos = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256, 3), np.uint8)
    for (s, zz, tx, ty) in keys:
        a = got[(s, zz, tx, ty)]
        if a is None:
            raise SystemExit(f"missing tile {tx},{ty}")
        mos[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = a.rgb
    ox, oy = x0 - tx0 * 256, y0 - ty0 * 256
    rgb = mos[oy:oy + W, ox:ox + W].copy()
    print(name, "imagery", len(keys), "tiles", f"{time.time()-t:.1f}s", I.summary())
    # DEM at every pixel centre
    n = 256 * 2 ** z
    P = int(round(pad_m / res))          # DEM pad (horizon of the cast shadows)
    px = (np.arange(-P, W + P) + x0 + 0.5)
    py = (np.arange(-P, W + P) + y0 + 0.5)
    lons = px / n * 360.0 - 180.0
    lats = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * py / n))))
    LON, LAT = np.meshgrid(lons, lats)
    D = demmod.Dem(os.path.join(HOME, "dem"))
    t = time.time()
    h = D.sample(LAT, LON, dem_zoom).astype(np.float32)
    print(name, "dem", f"{time.time()-t:.1f}s", D.stats_snapshot(), "h range", h.min(), h.max())
    np.savez_compressed(os.path.join(OUT, name + ".npz"), rgb=rgb, h=h, res=res, lat=lat, lon=lon,
                        x0=x0, y0=y0, z=z, pad=P)
    I.close()

if __name__ == "__main__":
    name, lat, lon = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    fetch(name, lat, lon, dem_zoom=int(sys.argv[4]) if len(sys.argv) > 4 else 15)

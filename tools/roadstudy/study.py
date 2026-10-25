"""Road study of BeamNG's official levels (read-only, from the game's level zips): per level, the
road-related objects, and cross-sections of the terrain (height + material) at right angles to the
AI path centrelines (road_invisible DecalRoads), every STEP m.
usage: python3 -I study.py <levels dir> <out dir> level [level ...]"""
import collections
import json
import math
import struct
import sys
import zipfile

import numpy as np

STEP = 10.0
OFFS = np.arange(-30.0, 30.01, 0.5)
ROADMAT_HINTS = ("asphalt", "road", "concrete", "tarmac", "pavement", "cobble", "brick", "parking")
DIRTMAT_HINTS = ("gravel", "dirt", "sand", "mud")


def items(z, level):
    for n in z.namelist():
        if n.startswith(f"levels/{level}/") and n.endswith("items.level.json"):
            for line in z.read(n).decode("utf-8", "replace").splitlines():
                line = line.strip()
                if line.startswith("{"):
                    try:
                        yield json.loads(line)
                    except ValueError:
                        pass


def terrain(z, level, objs):
    tb = next((o for o in objs if o.get("class") == "TerrainBlock"), None)
    if tb is None:
        return None
    tj = next((n for n in z.namelist() if n.startswith(f"levels/{level}/") and n.endswith(".terrain.json")), None)
    meta = json.loads(z.read(tj)) if tj else {}
    path = tb.get("terrainFile", "").lstrip("/")
    cand = [n for n in z.namelist() if n.lower() == path.lower()] or \
           [n for n in z.namelist() if n.startswith(f"levels/{level}/") and n.endswith(".ter")]
    b = z.read(cand[0])
    size = struct.unpack("<I", b[1:5])[0]
    h = np.frombuffer(b, "<u2", size * size, 5).reshape(size, size).astype(np.float32)
    lay = np.frombuffer(b, "u1", size * size, 5 + size * size * 2).reshape(size, size)
    sq = float(tb.get("squareSize", 1.0))
    maxh = float(tb.get("maxHeight", 2048.0))
    pos = tb.get("position", [0, 0, 0])
    mats = meta.get("materials", [])
    return {"h": h * (maxh / 65535.0) + pos[2], "lay": lay, "size": size, "sq": sq, "x0": pos[0], "y0": pos[1],
            "mats": mats}


def sample(t, x, y):
    """Bilinear height and nearest material at world (x, y) arrays; nan outside."""
    gx = (x - t["x0"]) / t["sq"]
    gy = (y - t["y0"]) / t["sq"]
    s = t["size"]
    ok = (gx >= 0) & (gy >= 0) & (gx < s - 1) & (gy < s - 1)
    gx = np.clip(gx, 0, s - 1.001)
    gy = np.clip(gy, 0, s - 1.001)
    ix, iy = gx.astype(int), gy.astype(int)
    fx, fy = gx - ix, gy - iy
    H = t["h"]
    hz = (H[iy, ix] * (1 - fx) * (1 - fy) + H[iy, ix + 1] * fx * (1 - fy) + H[iy + 1, ix] * (1 - fx) * fy
          + H[iy + 1, ix + 1] * fx * fy)
    m = t["lay"][np.rint(gy).astype(int).clip(0, s - 1), np.rint(gx).astype(int).clip(0, s - 1)]
    hz = np.where(ok, hz, np.nan)
    return hz, np.where(ok, m, 255)


def mat_kind(name):
    n = name.lower()
    if any(k in n for k in ROADMAT_HINTS):
        return "paved"
    if any(k in n for k in DIRTMAT_HINTS):
        return "dirt"
    return "other"


def nodes_of(o):
    ns = o.get("nodes") or []
    return [(float(n[0]), float(n[1]), float(n[2]), float(n[3]) if len(n) > 3 else 0.0) for n in ns if len(n) >= 3]


def walk(nodes):
    """Points every STEP m along a polyline with unit tangents and the local width."""
    out = []
    acc = 0.0
    for a, b in zip(nodes[:-1], nodes[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        if L < 1e-6:
            continue
        tx, ty = dx / L, dy / L
        s = (STEP - acc) % STEP
        while s < L:
            f = s / L
            out.append((a[0] + dx * f, a[1] + dy * f, tx, ty, a[3] + (b[3] - a[3]) * f))
            s += STEP
        acc = (acc + L) % STEP
    return out


def study(z, level):
    objs = list(items(z, level))
    classes = collections.Counter(o.get("class") for o in objs)
    decal = [o for o in objs if o.get("class") == "DecalRoad"]
    mats = collections.Counter(o.get("material") for o in decal)
    widths = collections.defaultdict(list)
    for o in decal:
        ns = nodes_of(o)
        if ns:
            widths[o.get("material")].append(float(np.median([n[3] for n in ns])))
    t = terrain(z, level, objs)
    res = {"level": level, "classes": {k: v for k, v in classes.most_common() if k in (
        "DecalRoad", "MeshRoad", "ProceduralMesh", "TSStatic", "Forest", "River", "WaterPlane", "GroundCover")},
           "decalMaterials": [(m, n, round(float(np.median(widths[m])), 2) if widths[m] else None)
                              for m, n in mats.most_common(25)]}
    if t is None:
        return res, None
    kinds = np.array([mat_kind(m) for m in t["mats"]] + ["other"] * (256 - len(t["mats"])))
    res["terrainMaterials"] = {m: mat_kind(m) for m in t["mats"]}
    res["terrain"] = {"size": t["size"], "sq": t["sq"]}
    # AI centrelines
    sections = []
    for o in decal:
        if o.get("material") != "road_invisible":
            continue
        ns = nodes_of(o)
        if len(ns) < 2:
            continue
        for x, y, tx, ty, w in walk(ns):
            px, py = -ty, tx
            hx = x + px * OFFS
            hy = y + py * OFFS
            hz, m = sample(t, hx, hy)
            if np.isnan(hz).any():
                continue
            sections.append((w, hz - hz[len(OFFS) // 2], kinds[m]))
    res["sections"] = len(sections)
    return res, sections


def summarise(sections):
    """Per AI-width bucket: paved / dirt half-width from the centre, cross profile percentiles."""
    out = {}
    buckets = collections.defaultdict(list)
    for w, dz, k in sections:
        b = int(round(w / 2.0) * 2)
        buckets[b].append((w, dz, k))
    c = len(OFFS) // 2
    for b, rows in sorted(buckets.items()):
        if len(rows) < 20:
            continue
        surf_hw, kind_ct = [], collections.Counter()
        prof = np.array([r[1] for r in rows])
        for w, dz, k in rows:
            kind = k[c]
            kind_ct[kind] += 1
            if kind in ("paved", "dirt"):
                left = c
                while left > 0 and k[left - 1] == kind:
                    left -= 1
                right = c
                while right < len(k) - 1 and k[right + 1] == kind:
                    right += 1
                surf_hw.append((OFFS[right] - OFFS[left]) / 2 + 0.25)
        absprof = np.abs(prof)
        # make profiles symmetric-insensitive: |dz| percentiles per offset
        p50 = np.nanmedian(prof, axis=0)
        out[b] = {
            "n": len(rows),
            "centreKind": dict(kind_ct),
            "surfaceWidthMedian": round(float(np.median(surf_hw)) * 2, 2) if surf_hw else None,
            "surfaceWidthP25_P75": [round(float(np.percentile(surf_hw, 25)) * 2, 2),
                                    round(float(np.percentile(surf_hw, 75)) * 2, 2)] if surf_hw else None,
            "absDz_median_at": {f"{o:+.0f}": round(float(np.median(absprof[:, i])), 3)
                                for i, o in enumerate(OFFS) if o in (-20, -12, -8, -6, -4, -2, 2, 4, 6, 8, 12, 20)},
            "signedDz_median_at": {f"{o:+.0f}": round(float(p50[i]), 3)
                                   for i, o in enumerate(OFFS) if o in (-20, -12, -8, -6, -4, -2, 2, 4, 6, 8, 12, 20)},
        }
    return out


def main():
    root, outdir = sys.argv[1], sys.argv[2]
    for level in sys.argv[3:]:
        zname = next((f for f in __import__("os").listdir(root) if f.lower() == level.lower() + ".zip"), None)
        if not zname:
            print("no zip for", level)
            continue
        z = zipfile.ZipFile(f"{root}/{zname}")
        lv = next((n.split("/")[1] for n in z.namelist() if n.lower().startswith(f"levels/{level.lower()}/")), level)
        res, secs = study(z, lv)
        if secs:
            res["byAiWidth"] = summarise(secs)
            np.savez_compressed(f"{outdir}/{lv}_sections.npz", w=np.array([s[0] for s in secs]),
                                dz=np.array([s[1] for s in secs]),
                                kind=np.array([[{"paved": 1, "dirt": 2}.get(x, 0) for x in s[2]] for s in secs], np.uint8))
        with open(f"{outdir}/{lv}.json", "w") as f:
            json.dump(res, f, indent=1)
        print(lv, "sections", res.get("sections"), "classes", res["classes"])


if __name__ == "__main__":
    main()

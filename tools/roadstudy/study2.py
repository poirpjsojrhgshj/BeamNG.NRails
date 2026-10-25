import json, sys, zipfile, os, math, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import study as st
root = sys.argv[1]
for level in sys.argv[2:]:
    zname = next(f for f in os.listdir(root) if f.lower() == level.lower() + ".zip")
    z = zipfile.ZipFile(f"{root}/{zname}")
    lv = next(n.split("/")[1] for n in z.namelist() if n.lower().startswith(f"levels/{level.lower()}/"))
    objs = list(st.items(z, lv)); t = st.terrain(z, lv, objs)
    kinds = np.array([st.mat_kind(m) for m in t["mats"]] + ["other"] * (256 - len(t["mats"])))
    rough, grades, edge = [], [], []
    for o in objs:
        if o.get("class") != "DecalRoad" or o.get("material") != "road_invisible":
            continue
        pts = st.walk(st.nodes_of(o))
        if len(pts) < 5:
            continue
        x = np.array([p[0] for p in pts]); y = np.array([p[1] for p in pts])
        zc, mc = st.sample(t, x, y)
        if np.isnan(zc).any():
            continue
        d2 = zc[2:] - 2 * zc[1:-1] + zc[:-2]          # second difference over 10 m steps
        rough.extend(np.abs(d2).tolist()); grades.extend((np.abs(np.diff(zc)) / st.STEP).tolist())
        # edge profile: find the paved/dirt edge on each side, then dz beyond it
        for (px, py, tx, ty, w), z0, k0 in zip(pts, zc, kinds[mc]):
            if k0 not in ("paved", "dirt"):
                continue
            for side in (-1, 1):
                offs = np.arange(0.0, 25.01, 0.5) * side
                hz, m = st.sample(t, px - ty * offs, py + tx * offs)
                kk = kinds[m]
                j = 0
                while j + 1 < len(kk) and kk[j + 1] == k0:
                    j += 1
                if j >= len(kk) - 13:
                    continue
                e = hz[j]
                edge.append((k0, abs(offs[j]), hz[j] - z0, hz[j + 2] - e, hz[j + 4] - e, hz[j + 8] - e, hz[j + 12] - e,
                             np.nanmin(hz[j:j + 9]) - e))
    rough = np.array(rough); grades = np.array(grades)
    print(f"== {lv}: centreline |2nd diff| per 10 m: p50 {np.median(rough):.3f} p90 {np.percentile(rough,90):.3f} m; grade p50 {np.median(grades)*100:.1f}% p95 {np.percentile(grades,95)*100:.1f}%")
    for k0 in ("paved", "dirt"):
        E = np.array([e[1:] for e in edge if e[0] == k0], float)
        if len(E) < 30:
            continue
        print(f"   {k0:5s} n={len(E):5d} half-width p50 {np.median(E[:,0]):.1f} m | edge vs centre p50 {np.median(E[:,1]):+.2f} | beyond edge dz +1m {np.median(E[:,2]):+.2f} +2m {np.median(E[:,3]):+.2f} +4m {np.median(E[:,4]):+.2f} +6m {np.median(E[:,5]):+.2f} | |dz| +4m p50 {np.median(np.abs(E[:,4])):.2f} p90 {np.percentile(np.abs(E[:,4]),90):.2f} | ditch (min within 4 m < -0.25) {np.mean(E[:,6] < -0.25)*100:.0f}%")

#!/usr/bin/env python3
"""NRails dev tool: the steps where a bridge deck meets the road on the ground, in road tiles kept by
tools/e2e_collect.py. A deck's top (roadmesh.deck, it collides) ends at an edge; just past an end edge (0.5 m out)
the road surface drawn there (roadmesh.build: draped LIFT over the graded physics ground) gives the ground's height.
A step |deck - ground| over a few cm is what a tyre hits at speed.

    .venv\\Scripts\\python.exe tools\\audit_road_joints.py [build\\e2e_keep] [--min 0.03]
"""
import argparse
import json
import os
import sys
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
import cdae  # noqa: E402

OUT_M = 0.5
BIN = 8.0


def tris_of(path, pos):
    d = cdae.read(path)
    m = next((m for m in d["meshes"] if isinstance(m, dict) and "verts" in m), None)
    if m is None:
        return np.zeros((0, 3, 3))
    a = cdae.mesh_arrays(m)
    V = a["verts"].astype(np.float64) + np.asarray(pos, np.float64)
    T = a["indices"].astype(np.int64).reshape(-1, 3)
    return V[T]                      # (n, 3, 3)


def shape_path(root, m, data, what):
    sl = (m.get("slots") or {}).get(what)        # [slot path, generation]: the pooled file holds the shape
    p = sl[0] if isinstance(sl, (list, tuple)) and sl else data[what]["shape"]
    return os.path.join(root, p.lstrip("/"))


class Surface:
    """Triangles binned for point queries: z of every triangle over (x, y)."""

    def __init__(self, tri):
        self.tri = tri
        self.bins = defaultdict(list)
        lo = np.floor(tri[:, :, :2].min(1) / BIN).astype(int)
        hi = np.floor(tri[:, :, :2].max(1) / BIN).astype(int)
        for i in range(len(tri)):
            for bx in range(lo[i, 0], hi[i, 0] + 1):
                for by in range(lo[i, 1], hi[i, 1] + 1):
                    self.bins[(bx, by)].append(i)

    def zs(self, x, y):
        out = []
        for i in self.bins.get((int(np.floor(x / BIN)), int(np.floor(y / BIN))), ()):
            a, b, c = self.tri[i]
            d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(d) < 1e-12:
                continue
            l1 = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / d
            l2 = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / d
            l3 = 1 - l1 - l2
            if min(l1, l2, l3) >= -1e-6:
                out.append(l1 * a[2] + l2 * b[2] + l3 * c[2])
        return out


def terrain_fn(root, meta):
    """The physics ground: the last terrain block the server sent (tiles.json "blocks", else the anchor's), its
    heightmap PNG (z = zBase + v q, row 0 north, posts squareSize apart, the block centred on (cx, cy)), bilinear.
    None without one."""
    from PIL import Image
    t = (meta.get("blocks") or [None])[-1] or meta["anchor"].get("terrain")
    if not t:
        return None
    hm = np.array(Image.open(os.path.join(root, t["heightmap"].lstrip("/"))), np.float64)
    z = t["zBase"] + hm * t["q"]
    n, sq = int(t["size"]), float(t["squareSize"])
    half = n * sq / 2
    cx, cy = float(t.get("cx", 0)), float(t.get("cy", 0))
    print(f"terrain: {t['heightmap'].split('/')[-1]} {n} px x {sq} m{' (provisional)' if meta.get('blocks') is None and meta['anchor'].get('provisional') else ''}")

    def at(x, y):
        i, j = (x - cx + half) / sq, (y - cy + half) / sq
        i0, j0 = int(np.floor(i)), int(np.floor(j))
        fi, fj = i - i0, j - j0
        if not (0 <= i0 < n - 1 and 0 <= j0 < n - 1):
            return np.nan
        r0, r1 = n - 1 - j0, n - 2 - j0
        return ((1 - fi) * (1 - fj) * z[r0, i0] + fi * (1 - fj) * z[r0, i0 + 1] + (1 - fi) * fj * z[r1, i0]
                + fi * fj * z[r1, i0 + 1])
    return at


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=os.path.join(ROOT, "build", "e2e_keep"))
    ap.add_argument("--min", type=float, default=0.03)
    a = ap.parse_args()
    meta = json.load(open(os.path.join(a.root, "tiles.json"), encoding="utf-8"))
    road, deck = [], []
    for m in meta["tiles"]:
        data = json.load(open(os.path.join(a.root, m["path"].lstrip("/")), encoding="utf-8"))
        for what, acc in (("road", road), ("deck", deck)):
            if isinstance(data.get(what), dict):
                acc.append(tris_of(shape_path(a.root, m, data, what), data[what]["pos"]))
    if not deck:
        print("no deck in these tiles")
        return
    road, deck = np.concatenate(road), np.concatenate(deck)
    n = np.cross(deck[:, 1] - deck[:, 0], deck[:, 2] - deck[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]
    # the slab's top (and the parapets' tops: skipped below); the shapes' triangles wind clockwise seen from their
    # front (cdae: Torque's order), so a face looking up has its right-hand normal down
    top = deck[n[:, 2] < -0.95]
    ztop = top[:, :, 2].mean(1)
    print(f"road triangles {len(road)}, deck top triangles {len(top)}")
    terrain = terrain_fn(a.root, meta)
    rs, ds = Surface(road), Surface(top)
    # the deck top's boundary edges (used by one top triangle), keyed by rounded end points
    count = defaultdict(list)
    for i, t in enumerate(top):
        for j in range(3):
            p, q = t[j], t[(j + 1) % 3]
            k = tuple(sorted((tuple(np.round(p, 2)), tuple(np.round(q, 2)))))
            count[k].append(i)
    steps, seams, gaps = [], [], []

    def ride(pt, out):
        """The largest jump of what a wheel rolls on (the highest of the terrain and the deck tops near pt's height)
        between samples 0.25 m apart, from 3 m on the deck to 14 m past its edge (an approach slab's length)."""
        prev, worst = None, 0.0
        for s in np.arange(-3.0, 14.01, 0.25):
            x, y = pt[:2] + out * s
            zt = terrain(x, y)
            cand = [z for z in ds.zs(x, y) if abs(z - pt[2]) < 1.5] + ([zt] if np.isfinite(zt) else [])
            if not cand:
                continue
            z = max(cand)
            if prev is not None:
                worst = max(worst, abs(z - prev))
            prev = z
        return worst
    for k, owners in count.items():
        if len(owners) != 1:
            continue
        p, q = np.array(k[0]), np.array(k[1])
        if np.hypot(*(q - p)[:2]) < 0.3:
            continue
        c = top[owners[0]].mean(0)
        mid = (p + q) / 2
        e = (q - p)[:2] / np.hypot(*(q - p)[:2])
        out = np.array([-e[1], e[0]])
        if np.dot(out, mid[:2] - c[:2]) < 0:
            out = -out
        # only edges across the road (its ends): the outward direction along the deck's long axis there (the main
        # axis of the deck top's vertices within 8 m)
        cen = top[:, :, :2].mean(1)
        near = top[np.hypot(*(cen - mid[:2]).T) < 8.0].reshape(-1, 3)[:, :2]
        if len(near) >= 3:
            w, vec = np.linalg.eigh(np.cov((near - near.mean(0)).T))
            if w[1] > 2.0 * w[0] and abs(float(np.dot(out, vec[:, 1]))) < 0.8:
                continue
        for f in (0.25, 0.5, 0.75):
            pt = p + (q - p) * f
            xi, yi = pt[:2] - out * 0.2
            zin = ds.zs(xi, yi)
            if any(0.7 < pt[2] - z < 1.1 for z in zin) or any(0.3 < z - pt[2] < 4.0 for z in zin):
                continue                    # a parapet's top, a pier cap under the slab
            x, y = pt[:2] + out * OUT_M
            near = [z for z in ds.zs(*(pt[:2] + out * 0.05)) if abs(z - pt[2]) < 1.0]
            if near:                        # another deck goes on there (a tile seam, the next part of a chain)
                seams.append((min(near, key=lambda z: abs(z - pt[2])) - pt[2], x, y, pt[2]))
                continue
            far = [z for z in ds.zs(*(pt[:2] + out * 1.5)) if abs(z - pt[2]) < 1.0]
            if far and not any(abs(z - pt[2]) < 1.0 for z in rs.zs(x, y)):
                gaps.append((x, y, pt[2]))  # a slot between two decks a wheel can fall into
                continue
            if any(abs(z - pt[2]) < 0.3 for z in ds.zs(x, y)):
                continue
            if terrain is not None:
                # (a side edge has its parapet over the inside point: skipped above) an end resting on the ground
                zg = terrain(x, y)
                if not abs(zg - pt[2]) < 1.5:
                    continue
            else:
                zs = [z for z in rs.zs(x, y) if abs(z - pt[2]) < 3.0]
                if not zs:
                    continue                    # no road there: a side edge
                zg = min(zs, key=lambda z: abs(z - pt[2]))
            steps.append((zg - pt[2], x, y, pt[2], ride(pt, out) if terrain is not None else 0.0))
    if seams:
        sz = np.abs([s[0] for s in seams])
        print(f"deck-to-deck seams: {len(sz)} samples, |dz| max {sz.max():.3f} m, > 2 cm: {int((sz > 0.02).sum())}")
        for s in sorted(seams, key=lambda s: -abs(s[0]))[:8]:
            if abs(s[0]) > 0.02:
                print(f"  dz {s[0]:+.2f} m at ({s[1]:.1f}, {s[2]:.1f}) z {s[3]:.2f}")
    print(f"slots between decks (a wheel falls in): {len(gaps)}")
    for g in gaps[:8]:
        print(f"  at ({g[0]:.1f}, {g[1]:.1f}) z {g[2]:.2f}")
    if not steps:
        print("no deck end meets a ground road here")
        return
    dz = np.array([s[0] for s in steps])
    print(f"deck end samples meeting a ground road: {len(dz)}")
    for lim in (0.03, 0.05, 0.10, 0.25, 0.5, 1.0):
        print(f"  |ground - deck| > {lim:4.2f} m: {int((np.abs(dz) > lim).sum())}")
    print("worst:")
    for s in sorted(steps, key=lambda s: -abs(s[0]))[:10]:
        print(f"  ground {'over' if s[0] > 0 else 'under'} the deck by {abs(s[0]):.2f} m at ({s[1]:.1f}, {s[2]:.1f}),"
              f" deck z {s[3]:.2f}")
    jumps = np.array([s[4] for s in steps])
    print(f"what a wheel rolls on across the joints (terrain or deck, 0.25 m apart): largest jump {jumps.max():.3f} m;"
          f" joints with a jump > 3 cm: {int((jumps > 0.03).sum())}, > 10 cm: {int((jumps > 0.10).sum())}")
    for s in sorted(steps, key=lambda s: -s[4])[:6]:
        print(f"  jump {s[4]:.2f} m at ({s[1]:.1f}, {s[2]:.1f})")


if __name__ == "__main__":
    main()

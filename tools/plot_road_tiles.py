#!/usr/bin/env python3
"""EarthNRails dev tool: a top view (PNG) of the road tiles kept by tools/e2e_collect.py: the road mesh grey (its
shade: its height), the decks' tops blue, the rails' collision red. Holes and joints show at a glance.

    .venv\\Scripts\\python.exe tools\\plot_road_tiles.py [build\\e2e_keep] --box X0 Y0 X1 Y1 [--px 0.25] [--out f.png]
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import audit_road_joints as A  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=os.path.join(ROOT, "build", "e2e_keep"))
    ap.add_argument("--box", type=float, nargs=4, required=True)
    ap.add_argument("--px", type=float, default=0.25, help="m per pixel")
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "road_top.png"))
    a = ap.parse_args()
    x0, y0, x1, y1 = a.box
    W, H = int((x1 - x0) / a.px), int((y1 - y0) / a.px)
    meta = json.load(open(os.path.join(a.root, "tiles.json"), encoding="utf-8"))
    layers = {"road": [], "deck": [], "railcol": [], "railtun": []}
    for m in meta["tiles"]:
        data = json.load(open(os.path.join(a.root, m["path"].lstrip("/")), encoding="utf-8"))
        for what, acc in layers.items():
            if isinstance(data.get(what), dict):
                acc.append(A.tris_of(A.shape_path(a.root, m, data, what), data[what]["pos"]))
    img = Image.new("RGB", (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(img)

    def pix(t):
        return [((p[0] - x0) / a.px, (y1 - p[1]) / a.px) for p in t]

    road = np.concatenate(layers["road"]) if layers["road"] else np.zeros((0, 3, 3))
    box = (road[:, :, 0].max(1) >= x0) & (road[:, :, 0].min(1) <= x1) & (road[:, :, 1].max(1) >= y0) & \
          (road[:, :, 1].min(1) <= y1)
    road = road[box]
    if len(road):
        z = road[:, :, 2].mean(1)
        lo, hi = np.percentile(z, 2), np.percentile(z, 98)
        for t, zz in zip(road, z):
            g = int(60 + 150 * np.clip((zz - lo) / max(hi - lo, 1e-6), 0, 1))
            dr.polygon(pix(t), fill=(g, g, g))
        print(f"road heights {lo:.1f}..{hi:.1f} m (dark..light)")
    for what, col in (("deck", (40, 90, 230)), ("railtun", (30, 160, 60)), ("railcol", (220, 30, 30))):
        if not layers[what]:
            continue
        t = np.concatenate(layers[what])
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        t = t[n[:, 2] < 0] if what == "deck" else t
        for tri in t:
            if tri[:, 0].max() < x0 or tri[:, 0].min() > x1 or tri[:, 1].max() < y0 or tri[:, 1].min() > y1:
                continue
            dr.polygon(pix(tri), outline=col)
    img.save(a.out)
    print(a.out)


if __name__ == "__main__":
    main()

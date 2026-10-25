#!/usr/bin/env python3
"""NRails dev tool: start the real server (earthd.py, a fresh user folder kept under build/, the real download
cache), drive the mod's protocol at a place (hello, prepare_anchor, commit, pose) and keep every road tile it sends
(JSON + shapes) in that folder for the audits (tools/audit_road_joints.py).

    .venv\\Scripts\\python.exe tools\\e2e_collect.py LAT LON [--tiles 25] [--wait 300] [--out build\\e2e_keep] [--hub]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server", "tests"))
from netclient import Client, stop_server  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--tiles", type=int, default=25)
    ap.add_argument("--wait", type=float, default=300.0)
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "e2e_keep"))
    ap.add_argument("--hub", action="store_true")
    a = ap.parse_args()
    shutil.rmtree(a.out, ignore_errors=True)
    os.makedirs(a.out)
    env = dict(os.environ, BNGE_RAILS="on", PYTHONUNBUFFERED="1")
    opts = (["--deshadow", "full", "--near-visual", "detail", "--airports", "on", "--sea", "on", "--trees", "on",
             "--buildings", "on"] if a.hub else ["--imagery", "off", "--trees", "off"])
    errlog = open(os.path.join(a.out, "server.log"), "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "server", "earthd.py"), "--port", "0",
                             "--user-dir", a.out, "--weather", "off", "--gravity", "off", "--update-check", "off"]
                            + opts, stdout=subprocess.PIPE, stderr=errlog, text=True, env=env)
    try:
        line = proc.stdout.readline()
        port = int(line.split("127.0.0.1:")[1].split()[0])
        c = Client(port)
        c.send({"type": "hello", "protocol": 4, "format": 3, "modVersion": "0.4.0"})
        c.until(lambda m: m["type"] == "hello", timeout=20)
        c.send({"type": "prepare_anchor", "requestId": 1, "lat": a.lat, "lon": a.lon})
        a1, _ = c.until(lambda m: m["type"] in ("anchor_ready", "anchor_error"), timeout=300)
        assert a1["type"] == "anchor_ready", a1
        aid = a1["anchorId"]
        c.send({"type": "commit_anchor", "anchorId": aid})
        c.send({"type": "commit_terrain", "anchorId": aid, "cx": 0, "cy": 0})
        pose = {"type": "pose", "anchorId": aid, "x": 0, "y": 0, "z": a1["groundZ"], "lat": a.lat, "lon": a.lon,
                "speed": 0, "vx": 0, "vy": 0}
        tiles, blocks, end, last = [], [], time.monotonic() + a.wait, 0.0
        while time.monotonic() < end and len(tiles) < a.tiles:
            if time.monotonic() - last > 1.0:
                c.send(pose)
                last = time.monotonic()
            try:
                m = c.recv(1)
            except TimeoutError:
                continue
            if m["type"] == "roads_tile":
                tiles.append(m)
            elif m["type"] in ("terrain_refresh", "terrain_ready") and m.get("heightmap"):
                blocks.append(m)            # the graded block in place of the provisional one
        with open(os.path.join(a.out, "tiles.json"), "w", encoding="utf-8") as f:
            json.dump({"anchor": a1, "tiles": tiles, "blocks": blocks}, f)
        print(f"{len(tiles)} road tiles kept in {a.out}")
        c.close()
    finally:
        stop_server(proc)
        proc.stdout.close()


if __name__ == "__main__":
    main()

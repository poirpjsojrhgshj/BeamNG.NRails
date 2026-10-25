#!/usr/bin/env python3
"""EarthNRails end-to-end check without the game: start the real server (earthd.py, a temporary user folder, the real
download cache), speak the mod's protocol (hello, prepare_anchor, commit, pose) at a place, collect the road tiles it
sends and report their rail meshes (rail / railcol / railx shapes, level crossings), reading each .cdae back.

    .venv\\Scripts\\python.exe tools\\e2e_rails.py [LAT LON] [--wait 240]
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.join(ROOT, "server", "tests"))
import cdae  # noqa: E402
from netclient import Client, stop_server  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", type=float, nargs="?", default=48.8443)
    ap.add_argument("lon", type=float, nargs="?", default=2.3744)
    ap.add_argument("--wait", type=float, default=240.0)
    ap.add_argument("--hub", action="store_true", help="the Hub's server options (buildings, trees, imagery on ...)")
    ap.add_argument("--log", default=os.path.join(ROOT, "build", "e2e_server.log"), help="the server's log")
    a = ap.parse_args()
    tmp = tempfile.TemporaryDirectory()
    env = dict(os.environ, BNGE_RAILS="on", PYTHONUNBUFFERED="1")
    opts = (["--deshadow", "full", "--near-visual", "detail", "--airports", "on", "--sea", "on", "--trees", "on",
             "--buildings", "on"] if a.hub else ["--imagery", "off", "--trees", "off"])
    os.makedirs(os.path.dirname(a.log), exist_ok=True)
    errlog = open(a.log, "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "server", "earthd.py"), "--port", "0",
                             "--user-dir", tmp.name, "--weather", "off", "--gravity", "off", "--update-check", "off"]
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
        c.send({"type": "pose", "anchorId": aid, "x": 0, "y": 0, "z": a1["groundZ"], "lat": a.lat, "lon": a.lon,
                "speed": 0, "vx": 0, "vy": 0})
        tiles, end = [], time.monotonic() + a.wait
        pose = {"type": "pose", "anchorId": aid, "x": 0, "y": 0, "z": a1["groundZ"], "lat": a.lat, "lon": a.lon,
                "speed": 0, "vx": 0, "vy": 0}
        last_pose = time.monotonic()
        while time.monotonic() < end:
            if time.monotonic() - last_pose > 1.0:      # the mod sends its pose all the time
                c.send(pose)
                last_pose = time.monotonic()
            try:
                m = c.recv(1)
            except TimeoutError:
                continue
            if m["type"] == "roads_tile":
                m["t"] = round(a.wait - (end - time.monotonic()), 1)    # s after the first pose
                tiles.append(m)
                if len(tiles) >= 25:
                    break
        report = {"anchor": aid, "groundZ": a1["groundZ"], "tiles": len(tiles), "with_rails": 0, "shapes": {},
                  "crossings": 0, "slots": 0,
                  "first_s": tiles[0]["t"] if tiles else None, "last_s": tiles[-1]["t"] if tiles else None}
        for m in tiles:
            path = os.path.join(tmp.name, m["path"].lstrip("/"))
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            kinds = [k for k in data if k.startswith("rail") and k != "railx_pts"]
            if kinds:
                report["with_rails"] += 1
            report["crossings"] += len(data.get("railx_pts", []))
            report["slots"] += sum(1 for k in (m.get("slots") or {}) if k.startswith("rail"))
            for k in kinds:
                f = os.path.join(tmp.name, data[k]["shape"].lstrip("/"))
                d = cdae.read(f)
                n = report["shapes"].setdefault(k, [0, 0])
                n[0] += 1
                n[1] += os.path.getsize(f)
                assert d is not None
        print(json.dumps(report, indent=1))
        c.close()
    finally:
        stop_server(proc)
        proc.stdout.close()
        try:
            tmp.cleanup()
        except OSError:
            pass


if __name__ == "__main__":
    main()

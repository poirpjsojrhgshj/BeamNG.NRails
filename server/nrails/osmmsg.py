"""NRails: the mod's "nrails_*" messages (earthd's dispatch, one NRails hook): OpenStreetMap's railways round the player
(nrails.osmrail) written as a file the game reads, and routes along them.

  nrails_osm {id, lat, lon, slat?, slon?, r_km?}  -> nrails_osm_ready {id, file, done, total, reach, n, error?} after
      each square loaded (the nearest first): the railways reachable along the tracks from (slat, slon) (the player's
      track) within r_km of (lat, lon), and their level crossings. The file: /temp/beamngEarth/nrails/osm_rails.json.
  nrails_osm_route {id, lat0, lon0, lat1, lon1} -> nrails_osm_route_result {id, points [[lat, lon]...], dist, error?}
"""
import asyncio
import json
import logging
import math
import os

from nrails import osmrail

log = logging.getLogger("earthd.nrails")
FILE = "osm_rails.json"
VFS_DIR = "/temp/beamngEarth/nrails/"
START_MAX_M = 300.0             # m the player's track may lie from OSM's nearest railway node
WRITE_EVERY = 4
_osm = [None]


def _get():
    if _osm[0] is None:
        from nrails import paths
        _osm[0] = osmrail.OsmRail(paths.default_cache_dir())
    return _osm[0]


def snapshot(g, lat, lon, slat, slon, r_km):
    """The file's content: {"lines", "xings", "reach"} (pure given the graph)."""
    r_m = r_km * 1000.0
    start = g.nearest(slat, slon, START_MAX_M) if slat is not None else None
    if start is not None:
        nodes = g.reachable(start, lat, lon, r_m)
    else:                       # (not on a track: every railway in the round, unconnected ones too)
        nodes = {n for n, (la, lo) in g.pos.items() if osmrail.dist_m(lat, lon, la, lo) <= r_m}
    xings = [[r[1], r[2], r[3], r[4]] for nid, r in g.xings.items() if nid in nodes]
    return {"lines": g.lines(nodes), "xings": xings, "reach": start is not None}


def _f(msg, k):
    try:
        v = float(msg.get(k))
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def on_message(daemon, msg):
    kind = msg.get("type")
    if kind == "nrails_osm":
        daemon.spawn(_area(daemon, msg))
    elif kind == "nrails_osm_route":
        daemon.spawn(_route(daemon, msg))


async def _area(daemon, msg):
    lat, lon = _f(msg, "lat"), _f(msg, "lon")
    if lat is None or lon is None:
        return
    slat, slon = _f(msg, "slat"), _f(msg, "slon")
    r_km = min(max(_f(msg, "r_km") or osmrail.RADIUS_KM, 5.0), 150.0)
    loop, send, rid = daemon.loop, daemon.send, msg.get("id")
    out_dir = os.path.join(daemon.s.root, "nrails")

    def write(done, total, error=None):
        snap = snapshot(_get().graph, lat, lon, slat, slon, r_km)
        os.makedirs(out_dir, exist_ok=True)
        tmp = os.path.join(out_dir, FILE + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, separators=(",", ":"))
        os.replace(tmp, os.path.join(out_dir, FILE))
        reply = {"type": "nrails_osm_ready", "id": rid, "file": VFS_DIR + FILE, "done": done, "total": total,
                 "reach": snap["reach"], "n": len(snap["lines"])}
        if error:
            reply["error"] = error
        loop.call_soon_threadsafe(send, reply)

    def work():
        # (the file written after the first square, every WRITE_EVERY then, and the last: the game decodes each, 2 MB
        # for a 100 km round)
        missing = _get().area(lat, lon, r_km,
                              on_progress=lambda d, t: (d == 1 or d == t or d % WRITE_EVERY == 0) and write(d, t))
        if missing:
            write(-1, -1, f"{missing} square(s) not loaded (OpenStreetMap busy or offline: asked again later)")
    try:
        await asyncio.get_running_loop().run_in_executor(None, work)
    except Exception as e:      # noqa: BLE001
        log.info("nrails osm: %s", e)
        send({"type": "nrails_osm_ready", "id": rid, "error": f"{type(e).__name__}: {e}"[:200]})


async def _route(daemon, msg):
    out = {"type": "nrails_osm_route_result", "id": msg.get("id"), "points": [], "dist": 0.0}
    p = [_f(msg, k) for k in ("lat0", "lon0", "lat1", "lon1")]
    if None in p:
        out["error"] = "bad request"
        daemon.send(out)
        return

    def work():
        g = _get().graph
        a, b = g.nearest(p[0], p[1], START_MAX_M), g.nearest(p[2], p[3], 2000.0)
        if a is None or b is None:
            return None, "no OpenStreetMap railway near " + ("the train" if a is None else "the destination")
        path, d = g.route(a, b)
        if path is None:
            return None, "no way along the tracks (without reversing)"
        return ([[round(x, 6), round(y, 6)] for x, y in osmrail.simplify([g.pos[n] for n in path], 3.0)], d), None
    try:
        res, err = await asyncio.get_running_loop().run_in_executor(None, work)
        if err:
            out["error"] = err
        else:
            out["points"], out["dist"] = res[0], round(res[1], 1)
    except Exception as e:      # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"[:200]
    daemon.send(out)

#!/usr/bin/env python3
"""Watch the game and the world server while the player plays (no input, no teleports): every second the frame times
(perfmon), the frames over core's HITCH_MS with the engine's per-subsystem split and our mod's parts, the simulation's
speed against the wall clock (a physics slowdown: the engine advances the sim less than real time), the player's
speed and height, the server's backlog, and the CPU and memory of the game and of the server with its worker
processes. Stops after --minutes or when the file <out>/STOP exists; then writes <out>/report.md.

    python3 tools/perf_watch.py --out ~/perf/session1 --minutes 15
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autodrive_perf as ad  # noqa: E402  (LUA_POLL, ProcSampler)
import mcp  # noqa: E402

POLL_S = 1.0
EXTRA_LUA = r'''
local v = getPlayerVehicle(0)
local vel = v and v:getVelocity()
local pos = v and v:getPosition()
local agl = nil
if pos then
  local g = be:getSurfaceHeightBelow(vec3(pos.x, pos.y, pos.z + 2))
  if g and g > -1e6 then agl = pos.z - g end
end
local st = beamngEarth_core._state() or {}
return jsonEncode({ speed = vel and math.sqrt(vel.x ^ 2 + vel.y ^ 2 + vel.z ^ 2) or 0, agl = agl,
  follows = st.followCount, anchor = st.anchorId, status = st.status })
'''


def lua_json(code):
    try:
        return json.loads(mcp.call("run_lua", {"code": code}))
    except Exception:           # a busy frame, the game gone: the next poll
        return None


def report(rows, out):
    """report.md: the spikes, the physics slowdowns, the loads."""
    lines = ["# Performance session", ""]
    if not rows:
        lines.append("No samples.")
        open(os.path.join(out, "report.md"), "w").write("\n".join(lines) + "\n")
        return
    frames = sum((r.get("perf") or {}).get("frames") or 0 for r in rows)
    secs = len(rows)
    fps = [((r.get("perf") or {}).get("frames") or 0) / POLL_S for r in rows]
    p99 = sorted((r.get("perf") or {}).get("p99") or 0 for r in rows)
    lines += [f"{secs} s sampled, {frames} frames, average {frames / max(1, secs):.0f} fps, "
              f"median of the per-second p99 frame {p99[len(p99) // 2]:.1f} ms, worst second's p99 {p99[-1]:.1f} ms.", ""]
    # spikes
    hs = []
    for r in rows:
        for h in r.get("hitches") or []:
            eng = sorted((h.get("engine") or {}).items(), key=lambda kv: -kv[1])
            hs.append((r["t"], h["ms"], eng[:3], h.get("mod") or {}, r.get("mph"), r.get("agl")))
    lines.append(f"## Frame spikes over 50 ms: {len(hs)} ({60 * len(hs) / max(1, secs):.1f} a minute)")
    causes = {}
    for _, ms, eng, mod, _, _ in hs:
        top = eng[0][0] if eng else "?"
        causes.setdefault(top, []).append(ms)
    for k, v in sorted(causes.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"- led by {k}: {len(v)}, median {sorted(v)[len(v) // 2]} ms, worst {max(v)} ms")
    lines.append("")
    lines.append("Worst 15:")
    for t, ms, eng, mod, mph, agl in sorted(hs, key=lambda h: -h[1])[:15]:
        e = ", ".join(f"{k} {v:.0f}" for k, v in eng)
        m = ", ".join(f"{k} {v}" for k, v in mod.items())
        lines.append(f"- t={t:.0f}s {ms} ms at {mph:.0f} mph{'' if agl is None else f', {agl:.0f} m up'}: {e}"
                     f"{' | mod: ' + m if m else ''}")
    lines.append("")
    # physics
    slow = [r for r in rows if ((r.get("perf") or {}).get("simWall") or 1) < 0.95]
    lines.append(f"## Physics slower than real time: {len(slow)} of {secs} seconds")
    for r in sorted(slow, key=lambda r: r["perf"]["simWall"])[:10]:
        p = r["perf"]
        lines.append(f"- t={r['t']:.0f}s sim/wall {p['simWall']:.2f} (engine's own {p.get('simRatio', 1):.2f}), "
                     f"{p.get('frames')} frames, max frame {p.get('maxMs', 0):.0f} ms, {r.get('mph', 0):.0f} mph")
    lines.append("")
    # loads
    def stat(key, field):
        v = [r["procs"][key][field] for r in rows if r.get("procs", {}).get(key, {}).get(field) is not None]
        return (sum(v) / len(v), max(v)) if v else (0, 0)
    gc, gm = stat("game", "cpu"), stat("game", "rssMB")
    sc, sm = stat("server", "cpu"), stat("server", "rssMB")
    lines += ["## Load", f"- game: CPU {gc[0]:.0f} % average, {gc[1]:.0f} % peak (100 % = one core); memory up to {gm[1]:.0f} MB",
              f"- server (with its workers): CPU {sc[0]:.0f} % average, {sc[1]:.0f} % peak; memory up to {sm[1]:.0f} MB "
              "(summed over its processes: shared pages count more than once)"]
    bl = [r.get("backlog") for r in rows if r.get("backlog") is not None]
    if bl:
        lines.append(f"- server backlog: {sum(bl) / len(bl):.0f} average, {max(bl)} peak")
    sp = [r.get("mph") or 0 for r in rows]
    lines.append(f"- player: up to {max(sp):.0f} mph; {sum(1 for r in rows if (r.get('agl') or 0) > 50)} s more than "
                 "50 m above the ground")
    open(os.path.join(out, "report.md"), "w").write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--minutes", type=float, default=15.0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    stop = os.path.join(a.out, "STOP")
    if os.path.exists(stop):
        os.remove(stop)
    lua_json("if not beamngEarth_perfmon then extensions.load('beamngEarth_perfmon') end "
             "beamngEarth_perfmon.snapshot() return jsonEncode({ok = true})")   # a fresh window
    if lua_json("beamngEarth_core.hitches() return jsonEncode({})") is None:
        print("the game's MCP server does not answer", file=sys.stderr)
    sampler = ad.ProcSampler()
    sampler.sample()
    rows, t0, end = [], time.time(), time.time() + a.minutes * 60
    with open(os.path.join(a.out, "samples.jsonl"), "w") as f:
        while time.time() < end and not os.path.exists(stop):
            tick = time.time()
            r = lua_json(ad.LUA_POLL)
            x = lua_json(EXTRA_LUA)
            if r:
                r["t"] = round(tick - t0, 1)
                if x:
                    r["mph"] = (x.get("speed") or 0) * 2.23694
                    r["agl"] = x.get("agl")
                    r["follows"], r["status"] = x.get("follows"), x.get("status")
                r["procs"] = sampler.sample()
                rows.append(r)
                f.write(json.dumps(r) + "\n")
                f.flush()
            time.sleep(max(0.0, POLL_S - (time.time() - tick)))
    report(rows, a.out)
    print(open(os.path.join(a.out, "report.md")).read())


if __name__ == "__main__":
    main()

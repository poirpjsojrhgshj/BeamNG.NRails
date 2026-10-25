#!/usr/bin/env python3
"""Simulated drive for unattended in-game testing (no driver needed).

Moves the player vehicle along a heading in small steps (teleport onto the ground each step),
while recording perfmon frame stats, terrain-follow commits, rebases and far-field state. At every
terrain commit it takes a before/after screenshot pair from a fixed free camera and reports the
pixel difference (how much the view visibly changed). Every N steps it also grabs a chase-view
screenshot for a visual timeline.

  python3 tools/sim_drive.py --out docs/research/sim1 --km 6 --heading 90 --speed 30
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def mcp(*a, timeout=30):
    r = subprocess.run([sys.executable, os.path.join(HERE, 'mcp.py'), *a], capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()


def lua_json(code):
    return json.loads(mcp('lua', code))


def status():
    return lua_json('return jsonEncode(loadstring("return "..beamngEarth_core.status())())')


def perf():
    return lua_json("if not beamngEarth_perfmon then extensions.load('beamngEarth_perfmon') end "
                    "return jsonEncode(beamngEarth_perfmon.snapshot())")


def ground(x, y):
    return float(mcp('lua', f'return string.format("%.3f", 9000-castRayStatic(vec3({x},{y},9000), vec3(0,0,-1), 20000))'))


def shot(path):
    p = mcp('call', 'screenshot').splitlines()[-1]
    for _ in range(50):
        if os.path.exists(p) and os.path.getsize(p) > 0:
            break
        time.sleep(0.1)
    time.sleep(0.3)
    shutil.copy(p, path)
    return path


def place_cam(x, y, z, dx, dy, dz):
    mcp('lua', f'commands.setFreeCamera(); core_camera.setPosition(0, vec3({x},{y},{z})); '
               f'core_camera.setRotation(0, quatFromDir(vec3({dx},{dy},{dz}):normalized(), vec3(0,0,1))); return 1')


def img_diff(a, b):
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None
    A = np.asarray(Image.open(a).convert('L'), dtype=np.float32)
    B = np.asarray(Image.open(b).convert('L'), dtype=np.float32)
    h, w = A.shape
    m = np.ones_like(A, bool)
    m[:int(h * 0.17), :int(w * 0.17)] = False   # free-camera help box
    m[int(h * 0.75):, int(w * 0.85):] = False    # gauges
    d = np.abs(A - B)
    return {'mean': round(float(d[m].mean()), 2), 'pct_gt30': round(float((d[m] > 30).mean() * 100), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--km', type=float, default=5.0)
    ap.add_argument('--heading', type=float, default=90.0, help='degrees, 0 = north, 90 = east')
    ap.add_argument('--speed', type=float, default=30.0, help='m/s of simulated travel')
    ap.add_argument('--step', type=float, default=1.0, help='seconds between steps')
    ap.add_argument('--timeline-every', type=int, default=20, help='chase screenshot every N steps (0 = off)')
    ap.add_argument('--commit-shots', type=int, default=3, help='max commits to capture before/after pairs for')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    log = open(os.path.join(a.out, 'samples.jsonl'), 'w')

    hx, hy = math.sin(math.radians(a.heading)), math.cos(math.radians(a.heading))
    st = status()
    p = st['player']
    x, y = p['x'], p['y']
    block, anchor = st.get('block'), st.get('anchorId')
    perf()  # reset window
    steps = int(a.km * 1000 / (a.speed * a.step))
    commits, rebases, shots = [], [], 0
    pending_pair = None
    t0 = time.time()
    for i in range(steps):
        x += hx * a.speed * a.step
        y += hy * a.speed * a.step
        g = ground(x, y)
        if g < -5000:  # no ground under the next point (outside terrain): wait for terrain-follow
            time.sleep(a.step)
            x -= hx * a.speed * a.step
            y -= hy * a.speed * a.step
            continue
        if pending_pair is None and len(commits) < a.commit_shots:
            # fixed camera 40 m above, 60 m behind the car, looking along the heading
            cam = (x - hx * 60, y - hy * 60, g + 40)
            place_cam(*cam, hx, hy, -0.35)
            time.sleep(0.4)
            pending_pair = {'cam': cam, 'before': shot(os.path.join(a.out, f'commit{len(commits)}_A.png'))}
        mcp('call', 'set_position', json.dumps({"pos": {"x": x, "y": y, "z": g + 1.5}}))
        if pending_pair:
            place_cam(*pending_pair['cam'], hx, hy, -0.35)
        time.sleep(a.step)
        st = status()
        pf = perf()
        rec = {'i': i, 't': round(time.time() - t0, 2), 'x': round(x), 'y': round(y), 'block': st.get('block'),
               'anchor': st.get('anchorId'), 'far': st.get('far'), 'gov': st.get('governor'),
               'perf': {k: pf.get(k) for k in ('fps', 'p50', 'p95', 'p99', 'maxMs', 'over50', 'simRatio', 'slowSimFrames', 'minSimRatio')}}
        if st.get('anchorId') != anchor:
            rebases.append({'i': i, 'from': anchor, 'to': st.get('anchorId'), 'ms': st.get('lastRebaseMs')})
            anchor = st.get('anchorId')
            pending_pair = None
            # the rebase moved the world origin: continue from the car's position in the new frame
            # (stepping on in the old frame's coordinates teleports 10 km away: a rebase every step)
            x, y = st['player']['x'], st['player']['y']
        elif st.get('block') != block:
            c = {'i': i, 'block': st.get('block'), 'ms': st.get('lastFollowMs')}
            if pending_pair:
                time.sleep(0.5)
                after = shot(os.path.join(a.out, f'commit{len(commits)}_B.png'))
                c['diff'] = img_diff(pending_pair['before'], after)
                pending_pair = None
            commits.append(c)
            print('commit', c, flush=True)
        block = st.get('block')
        rec['commitsSoFar'] = len(commits)
        log.write(json.dumps(rec) + '\n')
        log.flush()
        if a.timeline_every and i % a.timeline_every == 0 and pending_pair is None:
            place_cam(x - hx * 25, y - hy * 25, g + 9, hx, hy, -0.18)
            time.sleep(0.4)
            shot(os.path.join(a.out, f'timeline_{shots:03d}.png'))
            shots += 1

    # summary
    rows = [json.loads(l) for l in open(os.path.join(a.out, 'samples.jsonl'))]
    pf = [r['perf'] for r in rows if r['perf'].get('fps')]
    summary = {
        'km': a.km, 'steps': len(rows), 'commits': commits, 'rebases': rebases,
        'fps_mean': round(sum(p['fps'] for p in pf) / max(1, len(pf)), 1),
        'worst_frame_ms': round(max((p['maxMs'] or 0) for p in pf), 1) if pf else None,
        'frames_over50': sum((p['over50'] or 0) for p in pf),
        'min_sim_ratio_window': round(min((p['simRatio'] or 1) for p in pf), 3) if pf else None,
        'pops': (rows[-1].get('far') or {}).get('pops'), 'failed': (rows[-1].get('far') or {}).get('failed'),
    }
    json.dump(summary, open(os.path.join(a.out, 'summary.json'), 'w'), indent=1)
    print(json.dumps(summary, indent=1))
    mcp('lua', 'commands.setGameCamera(); return 1')


if __name__ == '__main__':
    main()

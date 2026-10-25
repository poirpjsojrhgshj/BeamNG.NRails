#!/usr/bin/env python3
"""Physics drive for unattended in-game testing: a ball rolled across the real ground.

sim_drive.py teleports the car in steps; this one spawns the stock `ball` vehicle, makes it the
player and pushes it (a velocity change toward the target speed and heading every tick, the way
core/funstuff.lua boosts vehicles), so it really rolls over the physics terrain at speed: terrain
follow, rebases, falling through or floating above the visible ground all show up as they would
for a driver. The user's car is frozen meanwhile (setActive(0), as vehicle pooling does: a parked
car would otherwise fall once the physics block follows the ball away) and is restored, re-entered
and teleported back to where it was at the end, whatever happens.

Per tick it records perfmon frame stats, the mod status (block, anchor, far field), the ball's
height above the physics ground, and which tile level is shown under the ball (it should be L-2:
the fine tiles that match the physics surface).

  python3 tools/ball_drive.py --out docs/research/ball1 --km 10 --speed 90 [--turn 3] [--heading 200]
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


def lua(code):
    return mcp('lua', code)


def lua_json(code):
    out = lua(code)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise RuntimeError('lua: ' + out[:300])


def shot(path):
    p = mcp('call', 'screenshot').splitlines()[-1]
    for _ in range(50):
        if os.path.exists(p) and os.path.getsize(p) > 0:
            break
        time.sleep(0.1)
    time.sleep(0.3)
    shutil.copy(p, path)


SETUP = r'''
local car = getPlayerVehicle(0)
if not car then return jsonEncode({error = 'no player vehicle'}) end
local s = loadstring('return ' .. beamngEarth_core.status())()
local p = car:getPosition()
BNGE_BALL = { carId = car:getID(), lat = s.player.lat, lon = s.player.lon }
local ball = core_vehicles.spawnNewVehicle('ball', { pos = vec3(p.x, p.y, p.z + 3), rot = quat(0, 0, 0, 1),
  autoEnterVehicle = true })
if not ball then return jsonEncode({error = 'ball spawn failed'}) end
BNGE_BALL.ballId = ball:getID()
car:setActive(0)
if not beamngEarth_perfmon then extensions.load('beamngEarth_perfmon') end
beamngEarth_perfmon.snapshot()
return jsonEncode(BNGE_BALL)'''

# push toward (vx, vy) at most `step` m/s per tick; then sample. Tile under the ball: the first
# shown live tile containing it, finest level first (keys are level_i_j, i = floor(x / size)).
TICK = r'''
local b = BNGE_BALL and getObjectByID(BNGE_BALL.ballId)
if not b then return jsonEncode({error = 'ball gone'}) end
local v = b:getVelocity()
local dvx, dvy = %f - v.x, %f - v.y
local m = math.sqrt(dvx * dvx + dvy * dvy)
if m > %f then dvx, dvy = dvx * %f / m, dvy * %f / m end
b:applyClusterVelocityScaleAdd(b:getRefNodeId(), 1, dvx, dvy, 0)
local p = b:getPosition()
local hit = castRayStatic(vec3(p.x, p.y, p.z + 500), vec3(0, 0, -1), 3000)
local ground = (hit and hit < 3000) and (p.z + 500 - hit) or nil
local ff = require('beamngEarth/farfield')
local under = nil
for l = -2, 7 do
  local size = 256 * 2 ^ l
  local t = ff._tile(l .. '_' .. math.floor(p.x / size) .. '_' .. math.floor(p.y / size))
  if t and t.shown and not t.failed then under = l; break end
end
local s = loadstring('return ' .. beamngEarth_core.status())()
return jsonEncode({ x = p.x, y = p.y, z = p.z, vx = v.x, vy = v.y, vz = v.z, ground = ground, under = under,
  block = s.block, anchor = s.anchorId, far = s.far, perf = beamngEarth_perfmon.snapshot() })'''

RESTORE = r'''
local st = BNGE_BALL
if not st then return 'nothing to restore' end
local car = getObjectByID(st.carId)
if car then car:setActive(1); be:enterVehicle(0, car) end
local ball = st.ballId and getObjectByID(st.ballId)
if ball then ball:delete() end
commands.setGameCamera()
local ok = car and beamngEarth_core.teleport(%r, %r)
BNGE_BALL = nil
return 'restored car ' .. tostring(st.carId) .. ' teleport ' .. tostring(ok)'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--km', type=float, default=5.0)
    ap.add_argument('--speed', type=float, default=40.0, help='target ground speed, m/s (134 = 300 mph)')
    ap.add_argument('--heading', type=float, default=None, help='degrees, 0 = north; default: a random-ish 200')
    ap.add_argument('--turn', type=float, default=0.0, help='heading change, degrees per second')
    ap.add_argument('--accel', type=float, default=40.0, help='max push, m/s^2')
    ap.add_argument('--lat', type=float, default=None, help='teleport here first (the car), then spawn the ball')
    ap.add_argument('--lon', type=float, default=None)
    ap.add_argument('--tick', type=float, default=0.25, help='seconds between pushes/samples')
    ap.add_argument('--shots', type=float, default=20.0, help='seconds between chase screenshots (0 = off)')
    ap.add_argument('--max-s', type=float, default=1800.0, help='give up after this many seconds')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    heading = 200.0 if a.heading is None else a.heading

    home = lua_json('local s = loadstring("return " .. beamngEarth_core.status())() '
                    'return jsonEncode({ lat = s.player.lat, lon = s.player.lon })')
    print('home', home, flush=True)
    if a.lat is not None and a.lon is not None:
        lua(f'return beamngEarth_core.teleport({a.lat}, {a.lon})')
        for _ in range(90):
            time.sleep(2)
            st = lua_json('local s = loadstring("return " .. beamngEarth_core.status())() '
                          'return jsonEncode({ done = s.far.done, q = s.far.queued, placing = s.placing })')
            if st.get('done') and (st.get('q') or 0) < 5:
                break
        time.sleep(3)
    setup = lua_json(SETUP)
    if 'error' in setup:
        sys.exit(setup['error'])
    print('setup', setup, flush=True)
    log = open(os.path.join(a.out, 'samples.jsonl'), 'w')
    rows, rebases, anchor = [], [], None
    driven, last_xy, t0, next_shot, n_shot = 0.0, None, time.time(), 5.0, 0
    try:
        time.sleep(1.0)  # the ball settles
        while driven < a.km * 1000 and time.time() - t0 < a.max_s:
            el = time.time() - t0
            hd = math.radians(heading + a.turn * el)
            vx, vy = a.speed * math.sin(hd), a.speed * math.cos(hd)
            step = a.accel * a.tick
            r = lua_json(TICK % (vx, vy, step, step, step))
            if 'error' in r:
                print('stop:', r['error'], flush=True)
                break
            r['t'] = round(el, 2)
            if r.get('anchor') != anchor:
                if anchor is not None:
                    rebases.append({'t': r['t'], 'from': anchor, 'to': r.get('anchor')})
                    print('rebase', rebases[-1], flush=True)
                anchor, last_xy = r.get('anchor'), None   # the frame changed: restart distance
            if last_xy:
                driven += math.hypot(r['x'] - last_xy[0], r['y'] - last_xy[1])
            last_xy = (r['x'], r['y'])
            r['driven'] = round(driven)
            r['air'] = round(r['z'] - r['ground'], 2) if r.get('ground') is not None else None
            rows.append(r)
            log.write(json.dumps(r) + '\n')
            log.flush()
            if a.shots and el >= next_shot:
                shot(os.path.join(a.out, f'chase_{n_shot:03d}.png'))
                n_shot, next_shot = n_shot + 1, el + a.shots
            time.sleep(max(0.0, a.tick - (time.time() - t0 - el)))
    finally:
        print(lua(RESTORE % (home['lat'], home['lon'])), flush=True)

    # summary
    pf = [r['perf'] for r in rows if (r.get('perf') or {}).get('fps')]
    speeds = [math.hypot(r['vx'], r['vy']) for r in rows]
    under = [r.get('under') for r in rows]
    n = max(1, len(rows))
    summary = {
        'km': round(driven / 1000, 2), 'seconds': rows[-1]['t'] if rows else 0, 'samples': len(rows),
        'speed_mean': round(sum(speeds) / n, 1), 'speed_max': round(max(speeds or [0]), 1),
        'rebases': rebases,
        'fps_mean': round(sum(p['fps'] for p in pf) / max(1, len(pf)), 1),
        'worst_frame_ms': round(max((p.get('maxMs') or 0) for p in pf), 1) if pf else None,
        'frames_over50': sum((p.get('over50') or 0) for p in pf),
        'min_sim_ratio': round(min((p.get('simRatio') or 1) for p in pf), 3) if pf else None,
        # the visible ground under the ball: L-2 = matches physics; anything else = mismatch
        'under_L-2_pct': round(100 * sum(1 for u in under if u == -2) / n, 1),
        'under_levels': {str(l): under.count(l) for l in sorted(set(under), key=lambda v: (v is None, v or 0))},
        'fell_through': sum(1 for r in rows if r.get('air') is not None and r['air'] < -3),
        'no_ground': sum(1 for r in rows if r.get('ground') is None),
        'queue_max': max(((r.get('far') or {}).get('queued') or 0) for r in rows) if rows else None,
        'pops': (rows[-1].get('far') or {}).get('pops') if rows else None,
        'failed': (rows[-1].get('far') or {}).get('failed') if rows else None,
    }
    json.dump(summary, open(os.path.join(a.out, 'summary.json'), 'w'), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()

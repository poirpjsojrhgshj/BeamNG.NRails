-- Runs the mod's edgeguard.lua step() (docs/ROADMAP.md "Robustness" 2) on a deterministic pseudo-random
-- schedule and prints every result, for server/tests/test_modsim.py, which runs the Python port
-- (modsim.EdgeGuard) on the same schedule.
--   luajit edgeguard_trace.lua <mod lua/ge/extensions dir> <steps> <seed>
-- One guard state runs through drives that approach, hold at and leave random 512 / 1024 blocks, on
-- the ground, airborne and falling, so the soft wall, the warning, the rescue and its rate limit run.
local dir, steps, seed = arg[1], tonumber(arg[2]), tonumber(arg[3])
package.path = dir .. '/?.lua;' .. package.path
local edgeguard = require('beamngEarth/edgeguard')

local x = seed
local function rnd()
  x = (x * 16807) % 2147483647
  return x / 2147483647
end

local g = edgeguard.new()
local clock = 0
local function f(v) return string.format('%.9f', v) end
for i = 1, steps do
  clock = clock + 0.05 + rnd() * 0.2
  local size = rnd() < 0.5 and 512 or 1024
  local cx, cy = math.floor((rnd() - 0.5) * 40) * 128, math.floor((rnd() - 0.5) * 40) * 128
  local x0, y0 = cx - size, cy - size -- the block's SW corner: HALF = size * 2 m / 2
  local box = { x0, y0, x0 + (size - 1) * 2, y0 + (size - 1) * 2 }
  -- positions from 300 m inside to 200 m past an edge, anywhere along it
  local side, along, off = math.floor(rnd() * 4), rnd(), (rnd() - 0.4) * 500
  local px, py
  if side == 0 then px, py = box[3] - off, box[2] + along * (box[4] - box[2])
  elseif side == 1 then px, py = box[1] + off, box[2] + along * (box[4] - box[2])
  elseif side == 2 then px, py = box[1] + along * (box[3] - box[1]), box[4] - off
  else px, py = box[1] + along * (box[3] - box[1]), box[2] + off end
  local vx, vy = (rnd() - 0.5) * 120, (rnd() - 0.5) * 120
  local gr = rnd()
  local ground = nil
  if gr < 0.6 then ground = rnd() * 3 elseif gr < 0.8 then ground = 3 + rnd() * 6 end
  local z = 1000 + (rnd() - 0.5) * 40
  local mode, setV, rescue = edgeguard.step(g, { clock = clock, x = px, y = py, z = z, vx = vx, vy = vy, box = box,
    ground = ground })
  print(table.concat({ 'E', i, mode, setV and f(setV[1]) or '-', setV and f(setV[2]) or '-',
    rescue and f(rescue[1]) or '-', rescue and f(rescue[2]) or '-', rescue and f(rescue[3]) or '-',
    g.lastGroundZ and f(g.lastGroundZ) or '-', g.holds, g.rescues }, ' '))
end

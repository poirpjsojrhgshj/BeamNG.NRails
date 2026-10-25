-- BeamNG.Earth dev tool: frame-time sampler. Not loaded by default; load with
--   extensions.load('beamngEarth_perfmon')
-- and poll beamngEarth_perfmon.snapshot() (returns stats since the previous snapshot).
-- Harness frames (docs/V1_4_SPEC.md 3.0): a test harness calls tagHarness() from the code it runs
-- through MCP; the next measured frame interval (the one that contains that MCP work, whichever
-- order the hooks run in) is counted in harnessFrames / harnessMaxMs and left out of every other
-- statistic.

local M = {}

local RING = 4096
local ring = {}
local n, sum, maxDt = 0, 0, 0
local over33, over50, over100 = 0, 0, 0
local worst = {} -- the 5 slowest frames this window: { ms, clock }
local clock = 0
-- Wall-clock frame interval: the engine's dtReal is smoothed/capped (a 60 ms terrain commit showed
-- up as a ~22 ms frame), so measure the real gap between onUpdate calls with hptimer.
local timer = hptimer and hptimer() or nil

-- Sim-time vs real-time per frame (onPreRender gets both): detects "time warp" where the engine
-- advances simulation less than real time on long frames.
local simSum, realSum, slowFrames, minRatio = 0, 0, 0, 1
local simWallSum, wallSum = 0, 0    -- sim time against the measured wall time (the engine's dtReal is smoothed: a
                                    -- physics slowdown hidden in it shows here)
local lastWallMs = nil
local harnessTag = false
local harnessFrames, harnessMax = 0, 0

local function reset()
  simSum, realSum, slowFrames, minRatio = 0, 0, 0, 1
  simWallSum, wallSum = 0, 0
  n, sum, maxDt = 0, 0, 0
  over33, over50, over100 = 0, 0, 0
  worst = {}
  harnessFrames, harnessMax = 0, 0
end

function M.tagHarness() harnessTag = true end

function M.onUpdate(dtReal)
  local ms = timer and timer:stopAndReset() or (dtReal or 0) * 1000
  clock = clock + ms / 1000
  if harnessTag then
    harnessTag = false
    harnessFrames = harnessFrames + 1
    if ms > harnessMax then harnessMax = ms end
    return
  end
  n = n + 1
  sum = sum + ms
  lastWallMs = ms
  ring[(n - 1) % RING + 1] = ms
  if ms > maxDt then maxDt = ms end
  if ms > 33.4 then over33 = over33 + 1 end
  if ms > 50 then over50 = over50 + 1 end
  if ms > 100 then over100 = over100 + 1 end
  if #worst < 5 or ms > worst[#worst][1] then
    worst[#worst + 1] = { ms, clock }
    table.sort(worst, function(a, b) return a[1] > b[1] end)
    if #worst > 5 then worst[6] = nil end
  end
end

function M.onPreRender(dtReal, dtSim)
  if not dtReal or dtReal <= 0 or not dtSim or dtSim <= 0 then return end -- paused
  simSum, realSum = simSum + dtSim, realSum + dtReal
  if lastWallMs then simWallSum, wallSum = simWallSum + dtSim, wallSum + lastWallMs / 1000; lastWallMs = nil end
  local r = dtSim / dtReal
  if r < 0.95 then slowFrames = slowFrames + 1 end
  if r < minRatio then minRatio = r end
end

function M.snapshot()
  local cnt = math.min(n, RING)
  local t = {}
  for i = 1, cnt do t[i] = ring[i] end
  table.sort(t)
  local function pct(p) return cnt > 0 and t[math.max(1, math.ceil(p * cnt))] or 0 end
  local out = {
    frames = n, avgMs = n > 0 and sum / n or 0, fps = sum > 0 and n / (sum / 1000) or 0,
    p50 = pct(0.5), p95 = pct(0.95), p99 = pct(0.99), maxMs = maxDt,
    over33 = over33, over50 = over50, over100 = over100, clock = clock,
    worst = worst,
    simRatio = realSum > 0 and simSum / realSum or 1, slowSimFrames = slowFrames, minSimRatio = minRatio,
    simWall = wallSum > 0 and simWallSum / wallSum or 1,
    harnessFrames = harnessFrames, harnessMaxMs = harnessMax,
  }
  reset()
  return out
end

return M

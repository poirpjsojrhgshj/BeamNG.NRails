-- luajit mod/tests/test_perfmon.lua  (perfmon.lua: frame statistics; V1_4_SPEC 3.0 harness tags)
-- A frame interval after tagHarness() (the MCP work of a test harness) is counted apart and left
-- out of every other statistic.
local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
dofile(dir .. '/stubs.lua')
local perfmon = require('beamngEarth/perfmon')

for _ = 1, 10 do perfmon.onUpdate(0.016) end
perfmon.tagHarness()
perfmon.onUpdate(0.2)    -- the harness frame
perfmon.onUpdate(0.02)
local s = perfmon.snapshot()
T.check(s.frames == 11, 'harness frame not counted as a frame (' .. s.frames .. ')')
T.near(s.maxMs, 20, 1e-9, 'harness frame left out of maxMs')
T.check(s.over50 == 0 and s.over100 == 0, 'and out of the hitch counters')
T.check(s.harnessFrames == 1, 'counted as a harness frame')
T.near(s.harnessMaxMs, 200, 1e-9, 'its duration reported apart')
T.near(s.fps, 11 / (0.18), 1e-6, 'fps over the other frames')
perfmon.onUpdate(0.2)
s = perfmon.snapshot()
T.check(s.harnessFrames == 0 and s.over100 == 1, 'untagged: a normal (slow) frame; window reset')
T.done('test_perfmon')

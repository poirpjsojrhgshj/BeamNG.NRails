-- luajit mod/tests/test_drophold.lua  (a car dropped far off the block waits for its ground, drophold.lua)
local T = dofile((arg[0]:match('^(.*)[/\\]') or '.') .. '/testlib.lua')
local d = require('beamngEarth/drophold')

local box = { -1000, -1000, 1000, 1000 }      -- the block's collidable area
local dt = 1 / 60

-- driving, even at 300 mph, never starts a hold; the first frame only records
local h = d.new()
T.check(d.observe(h, 0, 0, 10, 0, dt, 1, box, false) == nil, 'first frame: nothing to compare')
T.check(d.observe(h, 2.2, 0, 10, 134, dt, 1, box, false) == nil, '300 mph: no hold')
-- a jump within the block: there is collision there
T.check(d.observe(h, 600, 0, 10, 0, dt, 1, box, false) == nil, 'a jump onto the block: no hold')
-- a jump off the block (the game's drop at camera): hold where it was dropped
T.check(d.observe(h, 5000, 300, 80, 0, dt, 1, box, false) == 'start', 'dropped 4 km off the block: hold')
T.check(h.active and h.x == 5000 and h.y == 300 and h.z == 80, 'held at the drop point')
-- while the block is elsewhere: keep holding
T.check(d.step(h, 10.0, box, 'a', nil) == nil, 'block elsewhere: hold')
-- the block follows (a new box covering the car): a few frames for its collision, then the ground decides
local box2 = { 4000, -700, 6000, 1300 }
T.check(d.step(h, 11.0, box2, 'b', 40) == nil, 'just committed: wait for its collision')
T.check(d.step(h, 11.02, box2, 'b', 40) == nil, '... frame 2')
local act, z = d.step(h, 11.04, box2, 'b', 40)
T.check(act == 'release' and not h.active, 'dropped from 40 m over the ground: let go (it falls as the game drop does)')

-- the drop's own frame reports the jump as the car's speed (here 900 km in a frame): still a drop
h = d.new()
d.observe(h, 0, 0, 10, 0, dt, 1, box, false)
T.check(d.observe(h, 15000, 0, 10, 15000 / dt, dt, 1, box, false) == 'start', 'the jump frame\'s own speed does not excuse it')

-- the drop point under the new ground (a free camera below the not-yet-loaded hills): set on the ground
h = d.new()
d.observe(h, 0, 0, 10, 0, dt, 1, box, false)
d.observe(h, -9000, 0, 5, 0, dt, 1, box, false)
local box3 = { -10000, -1000, -8000, 1000 }
d.step(h, 1, box3, 'c', 120); d.step(h, 1.02, box3, 'c', 120)
act, z = d.step(h, 1.04, box3, 'c', 120)
T.check(act == 'place' and z == 120 + d.LIFT_M, 'under the ground: placed on it')

-- no ground under it yet (the block covers it, the ray misses): keep holding; past MAX_S let go
h = d.new()
d.observe(h, 0, 0, 10, 0, dt, 1, box, false)
d.observe(h, 3000, 0, 10, 0, dt, 1, box, false)
local box4 = { 2000, -1000, 4000, 1000 }
for i = 1, 5 do T.check(d.step(h, i * 0.02, box4, 'd', nil) == nil, 'no ground hit: hold ' .. i) end
T.check(d.step(h, d.MAX_S + 1, box4, 'd', nil) == 'timeout' and not h.active, 'past MAX_S: let go')

-- a block being built for it (a slow server, a first visit): the wait does not count towards MAX_S
h = d.new()
d.observe(h, 0, 0, 10, 0, dt, 1, box, false)
d.observe(h, 3000, 0, 10, 0, dt, 1, box, false)
T.check(d.step(h, 0, box, 'e', nil, true) == nil, 'building: hold')
T.check(d.step(h, d.MAX_S * 3, box, 'e', nil, true) == nil, 'still building after 3 x MAX_S: hold')
T.check(d.step(h, d.MAX_S * 3 + 5, box, 'e', nil, false) == nil, 'stopped building: the clock starts')
T.check(d.step(h, d.MAX_S * 4 + 6, box, 'e', nil, false) == 'timeout', 'MAX_S without progress: let go')

-- a new anchor (a rebase or the mod's own teleport moves the frame): never a jump
h = d.new()
d.observe(h, 0, 0, 10, 0, dt, 1, box, false)
T.check(d.observe(h, 9000, 0, 10, 0, dt, 2, box, false) == nil, 'anchor changed: no hold')
-- the mod placing the car itself (busy): no hold
T.check(d.observe(h, -9000, 0, 10, 0, dt, 2, box, true) == nil, 'busy: no hold')
-- no block at all yet: a jump is off any block
h = d.new()
d.observe(h, 0, 0, 10, 0, dt, 1, nil, false)
T.check(d.observe(h, 900, 0, 10, 0, dt, 1, nil, false) == 'start', 'no block: hold')
-- a rebase under a hold: held at the moved position
d.moved(h, 100, 50, 10)
T.check(h.x == 100 and h.y == 50, 'moved with the frame')
-- a drop near the block's edge, still on it: collision there, no hold
h = d.new()
d.observe(h, 0, 0, 10, 0, dt, 1, box, false)
T.check(d.observe(h, 990, 0, 10, 0, dt, 1, box, false) == nil, 'dropped near the edge, on the block: no hold')
-- the block edge margin: a point just inside the box but within EDGE_MARGIN is not yet covered
T.check(not d.inside(box, 990, 0, d.EDGE_MARGIN) and d.inside(box, 900, 0, d.EDGE_MARGIN), 'edge margin')

-- bridges and buildings (2026-10-19): with the ground in, the hold waits for the colliders around the car
h = d.new()
d.observe(h, 0, 0, 10, 0, dt, 1, box, false)
d.observe(h, 5000, 0, 30, 0, dt, 1, box, false)
local box4 = { 4000, -1000, 6000, 1000 }
d.step(h, 1, box4, 'd', 20, false, false); d.step(h, 1.02, box4, 'd', 20, false, false)
T.check(d.step(h, 1.04, box4, 'd', 20, false, false) == nil and h.active, 'ground in, colliders not: still held')
T.check(d.step(h, 5, box4, 'd', 20, false, false) == nil, '... 4 s later still held')
act = d.step(h, 6, box4, 'd', 20, false, true)
T.check(act == 'release' and not h.active, 'colliders in: let go')
h = d.new()
d.observe(h, 0, 0, 10, 0, dt, 1, box, false)
d.observe(h, 5000, 0, 30, 0, dt, 1, box, false)
d.step(h, 1, box4, 'd', 20, false, false); d.step(h, 1.02, box4, 'd', 20, false, false); d.step(h, 1.04, box4, 'd', 20, false, false)
T.check(d.step(h, 1.04 + d.NEAR_MAX_S - 1, box4, 'd', 20, false, false) == nil, 'colliders late: held up to NEAR_MAX_S')
T.check(d.step(h, 1.04 + d.NEAR_MAX_S + 0.1, box4, 'd', 20, false, false) == 'release', '... then let go anyway')
T.check(d.step(d.new(), 1, box4, 'd', 20, false, nil) == nil, 'no hold active: nothing')
-- a drop onto the block where the colliders are not in yet (a bridge there): held too; where they are: not
h = d.new()
d.observe(h, 0, 0, 10, 0, dt, 1, box, false)
T.check(d.observe(h, 600, 0, 10, 0, dt, 1, box, false, function() return false end) == 'start', 'onto the block, colliders missing: hold')
h = d.new()
d.observe(h, 0, 0, 10, 0, dt, 1, box, false)
T.check(d.observe(h, 600, 0, 10, 0, dt, 1, box, false, function() return true end) == nil, 'onto the block, colliders in: no hold')

T.done('test_drophold')

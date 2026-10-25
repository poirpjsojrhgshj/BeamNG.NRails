-- Drop hold (the user, 2026-10-18: "if someone teleports far away using the camera, i want it to pause physics
-- until the collision generates under the car"). The game's "drop player at camera" (commands.dropPlayerAtCamera,
-- also its NoReset variant) or a switch to a vehicle far away puts the car where there is no collision yet: off the
-- physics block, which follows the player only once the server has built the next one (~1-5 s). The car fell
-- through the world meanwhile.
--
-- A jump of more than JUMP_M in one frame (not explained by the car's own speed, the anchor unchanged: a rebase or
-- the mod's own teleport moves the frame, not the car) to a place outside the block's collidable area starts a
-- hold: the game's own pause (simTimeAuthority, core.lua) while the mod runs on (the block that follows the player is
-- built and committed as usual; a rebase waits for the resume). Holding the car by setting its position every frame
-- damaged it (2026-10-18).
-- The hold ends once the committed block covers the car (EDGE_MARGIN inside) and a ray down meets ground there:
-- the car is set on the ground if the drop point is under it, else let go where it was dropped (a drop from the
-- air falls, as the game's drop does). MAX_S at most, then it is let go anyway.
--
-- Pure decisions here (tests: mod/tests/test_drophold.lua); core.lua does the vehicle calls.
local M = {}

M.JUMP_M = 250          -- m in one frame: a drop / switch, not driving (1000 mph is ~7 m a frame at 60 fps)
M.EDGE_MARGIN = 40      -- m inside the block's collidable box before the ground there counts
M.SETTLE_FRAMES = 3     -- frames after the covering block's commit (its collision applies the next frame)
M.MAX_S = 30            -- s without progress (no block being built: offline, a server that cannot build there): let go
M.UNDER_M = 0.5         -- the drop point this close over the ground or under it: the car goes onto the ground
M.LIFT_M = 1.0          -- ... this far above it
-- Bridges and buildings too (the user, 2026-10-19: "The teleport pause works for the ground but bridges and buildings
-- take longer to get collision and when it unpauses they often dont"): with the ground in, the hold also waits for the
-- road tiles within NEAR_M (their decks, tunnels, sidewalks and buildings made and solid: roads.readyAround), at most
-- NEAR_MAX_S, then lets go anyway.
M.NEAR_M = 300
M.NEAR_MAX_S = 20

function M.new() return { active = false } end

local function inside(box, x, y, m)
  return box ~= nil and x >= box[1] + m and x <= box[3] - m and y >= box[2] + m and y <= box[4] - m
end
M.inside = inside

-- Each frame with the player's position (x, y, z in the anchor frame), speed (m/s), the frame's dt (s), the
-- anchor id, the block's collidable box ({x0, y0, x1, y1} or nil) and busy (the mod is placing or rebasing the car
-- itself). Returns 'start' when a hold begins (h.x, h.y, h.z: where to hold), else nil.
-- nearReady(x, y): optional, are the colliders around (x, y) in (roads.readyAround)? A drop onto the block where they
-- are not holds too (a bridge or building there had no collision yet).
function M.observe(h, x, y, z, speed, dt, anchorId, box, busy, nearReady)
  local last = h.last
  h.last = { x = x, y = y, z = z, anchorId = anchorId, speed = speed or 0 }
  if h.active or busy or not last or last.anchorId ~= anchorId then return nil end
  local d = math.sqrt((x - last.x) ^ 2 + (y - last.y) ^ 2)
  -- the speed of the frame before: in the drop's own frame the engine reports the jump itself as the car's velocity
  -- (thousands of m/s), which excused every drop (the user's first try, 2026-10-18: "physics didnt pause")
  if d <= M.JUMP_M or d <= last.speed * (dt or 0) * 5 then return nil end
  -- dropped onto the block (up to its edge): its ground is there, and the bridges and buildings too unless nearReady says
  if inside(box, x, y, 0) and (not nearReady or nearReady(x, y)) then return nil end
  h.active, h.x, h.y, h.z, h.since, h.settle, h.nearSince = true, x, y, z, nil, nil, nil
  return 'start'
end

-- The frame's anchor changed under a hold (a rebase moved the car with the frame): hold at its new position.
function M.moved(h, x, y, z)
  if h.active then h.x, h.y, h.z = x, y, z end
end

-- While holding, each frame: now (s), the block's box, blockSerial (changes at every block commit), groundZ (the
-- ground under the hold point from a ray down, nil = no hit), building (see above). Returns nil (keep holding), 'release' (let go where
-- it is), 'place', z (set the car on the ground at z) or 'timeout'.
-- building: a block for the car is being prepared (a terrain request out, the server connected): the wait is not
-- counted (a slow server or a first visit took 48 s, and the car fell when 30 s ran out, 2026-10-18).
-- near: the colliders around the hold point are in (roads.readyAround; nil counts as yes).
function M.step(h, now, box, blockSerial, groundZ, building, near)
  if not h.active then return nil end
  h.since = (building or h.since == nil) and now or h.since
  if now - h.since > M.MAX_S then
    h.active = false
    return 'timeout'
  end
  if not inside(box, h.x, h.y, M.EDGE_MARGIN) then
    h.settle = nil
    return nil
  end
  if h.settle == nil or h.settle.serial ~= blockSerial then
    h.settle = { serial = blockSerial, frames = 0 }
  end
  h.settle.frames = h.settle.frames + 1
  if h.settle.frames < M.SETTLE_FRAMES or groundZ == nil then return nil end
  if near == false then
    h.nearSince = h.nearSince or now
    if now - h.nearSince < M.NEAR_MAX_S then return nil end
  end
  h.active = false
  if h.z < groundZ + M.UNDER_M then return 'place', groundZ + M.LIFT_M end
  return 'release'
end

function M.cancel(h) h.active = false end

return M

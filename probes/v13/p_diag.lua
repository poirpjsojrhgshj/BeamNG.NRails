-- Which diagonal does BeamNG's terrain collision use per square? (V1_3 risk #1)
-- Square corners flat at H, NE corner H+1. Probe (0.8,0.4) and (0.4,0.8):
-- SW-NE split -> +0.4 / +0.4 ; SE-NW split -> +0.2 / +0.2 ; bilinear -> +0.32
local tb = scenetree.findObject("bngEarthTerrain")
local p = tb:getPosition()
local S = 2.0
local sq = { {600, 600}, {610, 611}, {621, 620}, {631, 631} }
local H = 60
for _, s in ipairs(sq) do
  local gx, gy = s[1], s[2]
  for dx = -1, 2 do for dy = -1, 2 do tb:setHeight(gx + dx, gy + dy, H) end end
  tb:setHeight(gx + 1, gy + 1, H + 1)
end
tb:updateGrid(vec3(590, 590), vec3(640, 640))
_G.__diag = { p = p, sq = sq }
return "ok"

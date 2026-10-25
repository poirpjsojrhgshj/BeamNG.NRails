local d = _G.__diag
local p, S = d.p, 2.0
local out = {}
local function z(x, y) return 9000 - castRayStatic(vec3(x, y, 9000), vec3(0, 0, -1), 20000) end
for _, s in ipairs(d.sq) do
  local gx, gy = s[1], s[2]
  local bx, by = p.x + gx * S, p.y + gy * S
  local base = z(bx + 0.02, by + 0.02)
  local a = z(bx + 0.8 * S, by + 0.4 * S) - base
  local b = z(bx + 0.4 * S, by + 0.8 * S) - base
  table.insert(out, string.format("sq(%d,%d) parity=%d  (0.8,0.4)=%+.3f (0.4,0.8)=%+.3f  -> %s", gx, gy, bit.band(bit.bxor(gx, gy), 1), a, b,
    (math.abs(a - 0.4) < 0.03 and math.abs(b - 0.4) < 0.03) and "SW-NE" or ((math.abs(a - 0.2) < 0.03 and math.abs(b - 0.2) < 0.03) and "SE-NW" or "other")))
end
return table.concat(out, "\n")

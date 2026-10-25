-- Spatial index of far tiles for the dev tools (docs/DEVTOOLS.md "Cost rules": outlines and the
-- mini-map look up the tiles near the player without a loop over every tile). Pure Lua, runs under
-- plain luajit.
--
-- One hash grid per tile level. A tile goes into the cell of its footprint's centre; the cell edge
-- is max(tile size, minCell), so a level never has more cells than tiles. A query visits, per
-- level, the cells a disc (grown by the largest half-footprint stored at that level) touches - or,
-- when that range holds more cells than the level has occupied, the occupied cells instead. So a
-- query costs O(min(range, occupied cells)) per level, never O(all tiles) for a small radius.
-- Entries are keyed by an id (the tile object's id). Items are the caller's tables with a footprint
-- x0, y0, x1, y1 and a level, read at insert time: after the footprints move (a rebase), clear and
-- insert again.

local M = {}

local floor, max, min, huge = math.floor, math.max, math.min, math.huge

M.MIN_CELL = 512      -- m; fine levels (L-2 64 m, L-1 128 m, L0 256 m) share 512 m cells
local OFF = 2 ^ 20    -- cell index offset (|i| < 2^20 cells = 500000 km at 512 m)
local SPAN = 2 ^ 21

local Index = {}
Index.__index = Index

function M.new(minCell)
  return setmetatable({ minCell = minCell or M.MIN_CELL, levels = {}, where = {}, n = 0, version = 0 }, Index)
end

local function cellKey(i, j) return (i + OFF) * SPAN + (j + OFF) end

local function levelOf(self, level)
  local lv = self.levels[level]
  if not lv then
    local size = 256 * 2 ^ level
    lv = { cell = max(size, self.minCell), cells = {}, nCells = 0, n = 0, half = 0 }
    self.levels[level] = lv
  end
  return lv
end

-- Squared distance from (x, y) to a footprint (0 inside).
local function dist2(item, x, y)
  local dx = max(item.x0 - x, 0, x - item.x1)
  local dy = max(item.y0 - y, 0, y - item.y1)
  return dx * dx + dy * dy
end
M.dist2 = dist2

function Index:remove(id)
  local w = self.where[id]
  if not w then return false end
  local lv = self.levels[w.level]
  local c = lv.cells[w.key]
  c[id] = nil
  if next(c) == nil then
    lv.cells[w.key] = nil
    lv.nCells = lv.nCells - 1
  end
  lv.n = lv.n - 1
  self.where[id] = nil
  self.n = self.n - 1
  self.version = self.version + 1
  return true
end

function Index:insert(id, item)
  if self.where[id] then self:remove(id) end
  local level = tonumber(item.level) or 0
  local lv = levelOf(self, level)
  local cx, cy = 0.5 * (item.x0 + item.x1), 0.5 * (item.y0 + item.y1)
  local key = cellKey(floor(cx / lv.cell), floor(cy / lv.cell))
  local c = lv.cells[key]
  if not c then
    c = {}
    lv.cells[key] = c
    lv.nCells = lv.nCells + 1
  end
  c[id] = item
  lv.n = lv.n + 1
  lv.half = max(lv.half, 0.5 * (item.x1 - item.x0), 0.5 * (item.y1 - item.y0))
  self.where[id] = { level = level, key = key }
  self.n = self.n + 1
  self.version = self.version + 1
end

function Index:clear()
  self.levels, self.where, self.n = {}, {}, 0
  self.version = self.version + 1
end

function Index:count() return self.n end

function Index:get(id)
  local w = self.where[id]
  if not w then return nil end
  return self.levels[w.level].cells[w.key][id]
end

-- Items whose footprint is within r of (x, y), appended to `out` (a new table if nil) as
-- { item = item, id = id, d2 = squared distance }. Unordered. Returns out and the number of cells
-- visited (for the cost tests). levelMin: skip levels below it (the mini-map's sub-pixel tiles).
function Index:query(x, y, r, out, levelMin)
  out = out or {}
  local visited = 0
  local r2 = r * r
  for level, lv in pairs(self.levels) do
    if lv.n > 0 and (not levelMin or level >= levelMin) then
      local g, reach = lv.cell, r + lv.half
      local i0, i1 = floor((x - reach) / g), floor((x + reach) / g)
      local j0, j1 = floor((y - reach) / g), floor((y + reach) / g)
      local function scan(c)
        for id, item in pairs(c) do
          local d2 = dist2(item, x, y)
          if d2 <= r2 then out[#out + 1] = { item = item, id = id, d2 = d2 } end
        end
      end
      if (i1 - i0 + 1) * (j1 - j0 + 1) > lv.nCells then
        for key, c in pairs(lv.cells) do
          local i, j = floor(key / SPAN) - OFF, key % SPAN - OFF
          visited = visited + 1
          if i >= i0 and i <= i1 and j >= j0 and j <= j1 then scan(c) end
        end
      else
        for i = i0, i1 do
          for j = j0, j1 do
            visited = visited + 1
            local c = lv.cells[cellKey(i, j)]
            if c then scan(c) end
          end
        end
      end
    end
  end
  return out, visited
end

-- The finest item whose footprint contains (x, y) and for which accept(item) is true (nil = any).
function Index:at(x, y, accept)
  local best, bestLevel = nil, huge
  for level, lv in pairs(self.levels) do
    if lv.n > 0 and level < bestLevel then
      local g, reach = lv.cell, lv.half
      for i = floor((x - reach) / g), floor((x + reach) / g) do
        for j = floor((y - reach) / g), floor((y + reach) / g) do
          local c = lv.cells[cellKey(i, j)]
          if c then
            for _, item in pairs(c) do
              if x >= item.x0 and x < item.x1 and y >= item.y0 and y < item.y1
                and level < bestLevel and (not accept or accept(item)) then
                best, bestLevel = item, level
              end
            end
          end
        end
      end
    end
  end
  return best
end

-- Sort query results nearest first and keep at most n.
function M.nearest(list, n)
  table.sort(list, function(a, b)
    if a.d2 ~= b.d2 then return a.d2 < b.d2 end
    return a.id < b.id
  end)
  for i = #list, (n or #list) + 1, -1 do list[i] = nil end
  return list
end

M.Index = Index
return M

-- BeamNG.NRails: itineraries (the user's run, 2026-10-26: "itineraire"): the way along the loaded tracks from the
-- player's train to a point picked on the turnout diagram, and the route each turnout on it must be set to.
-- The tracks are the tiles' centre lines (t.railLines: flat x, y, z rows, a piece per track and tile, ends meeting at
-- the turnouts' nodes and the tile seams). They are sampled every STEP_M; a line's end within LINK_M of another
-- line's sample is the same node (a turnout's node, a seam, two tiles' overlapping pieces). The search runs on
-- directed edges and never turns more than TURN_DEG between two (a train cannot reverse at a turnout). Pure.
local M = {}

M.STEP_M = 5
M.LINK_M = 2.5
M.TURN_DEG = 75
M.ROUTE_HIT_M = 1.6     -- m from the way to a route's zone end: the way takes that route
M.NODE_HIT_M = 3.0      -- m from the way to a turnout's node: the way goes through it

-- The graph of the lines: { x = {}, y = {}, adj = { [node] = { node, ... } } } (samples merged at the links).
function M.graph(rows)
  local px, py, line = {}, {}, {}
  local runs = {}
  for _, row in ipairs(rows or {}) do
    local n = math.floor(#row / 3)
    if n >= 2 then
      local first = #px + 1
      local lastx, lasty
      for i = 1, n do
        local x, y = row[3 * i - 2], row[3 * i - 1]
        local keep = (i == 1 or i == n)
        if not keep and lastx then keep = (x - lastx) ^ 2 + (y - lasty) ^ 2 >= M.STEP_M ^ 2 end
        if keep then
          px[#px + 1], py[#py + 1] = x, y
          lastx, lasty = x, y
          line[#px] = #runs + 1
        end
      end
      runs[#runs + 1] = { first, #px }
    end
  end
  local cell = 10
  local grid = {}
  local function gkey(cx, cy) return cx .. '_' .. cy end
  for i = 1, #px do
    local k = gkey(math.floor(px[i] / cell), math.floor(py[i] / cell))
    grid[k] = grid[k] or {}
    table.insert(grid[k], i)
  end
  local parent = {}
  for i = 1, #px do parent[i] = i end
  local function find(a)
    while parent[a] ~= a do parent[a] = parent[parent[a]]; a = parent[a] end
    return a
  end
  for li, r in ipairs(runs) do
    for _, e in ipairs({ r[1], r[2] }) do
      local cx, cy = math.floor(px[e] / cell), math.floor(py[e] / cell)
      local best, bd = nil, M.LINK_M ^ 2
      for dx = -1, 1 do
        for dy = -1, 1 do
          for _, j in ipairs(grid[gkey(cx + dx, cy + dy)] or {}) do
            if line[j] ~= li then
              local d = (px[j] - px[e]) ^ 2 + (py[j] - py[e]) ^ 2
              if d <= bd then best, bd = j, d end
            end
          end
        end
      end
      if best then
        local a, b = find(best), find(e)
        if a ~= b then parent[b] = a end
      end
    end
  end
  local g = { x = {}, y = {}, adj = {}, of = {} }
  local sx, sy, sn = {}, {}, {}
  for i = 1, #px do
    local r = find(i)
    sx[r] = (sx[r] or 0) + px[i]; sy[r] = (sy[r] or 0) + py[i]; sn[r] = (sn[r] or 0) + 1
    g.of[i] = r
  end
  for r, n in pairs(sn) do g.x[r], g.y[r] = sx[r] / n, sy[r] / n end
  local function link(a, b)
    if a == b then return end
    g.adj[a] = g.adj[a] or {}
    for _, c in ipairs(g.adj[a]) do if c == b then return end end
    table.insert(g.adj[a], b)
  end
  for _, r in ipairs(runs) do
    for i = r[1], r[2] - 1 do
      local a, b = g.of[i], g.of[i + 1]
      link(a, b); link(b, a)
    end
  end
  return g
end

-- The node nearest to (x, y) and its distance.
function M.nearest(g, x, y)
  local best, bd = nil, math.huge
  for n, nx in pairs(g.x) do
    local d = (nx - x) ^ 2 + (g.y[n] - y) ^ 2
    if d < bd then best, bd = n, d end
  end
  return best, math.sqrt(bd)
end

local function push(h, e)
  h[#h + 1] = e
  local i = #h
  while i > 1 do
    local p = math.floor(i / 2)
    if h[p][1] <= h[i][1] then break end
    h[p], h[i] = h[i], h[p]
    i = p
  end
end
local function pop(h)
  local top = h[1]
  local last = table.remove(h)
  if #h > 0 then
    h[1] = last
    local i = 1
    while true do
      local l, r, m = 2 * i, 2 * i + 1, i
      if l <= #h and h[l][1] < h[m][1] then m = l end
      if r <= #h and h[r][1] < h[m][1] then m = r end
      if m == i then break end
      h[i], h[m] = h[m], h[i]
      i = m
    end
  end
  return top
end

-- The way from (x, y), the train facing (fx, fy) (0, 0: either way), to (tx, ty): a list of points {x, y}, or nil.
-- Dijkstra on directed edges, never more than TURN_DEG between two.
function M.find(g, x, y, fx, fy, tx, ty)
  local s = M.nearest(g, x, y)
  local t = M.nearest(g, tx, ty)
  if not s or not t then return nil end
  if s == t then return { { g.x[s], g.y[s] } } end
  local cosMax = math.cos(math.rad(M.TURN_DEG))
  local function dir(a, b)
    local dx, dy = g.x[b] - g.x[a], g.y[b] - g.y[a]
    local l = math.sqrt(dx * dx + dy * dy)
    if l < 1e-6 then return 0, 0, 0 end
    return dx / l, dy / l, l
  end
  local h, dist, prev, edge = {}, {}, {}, {}
  local fl = math.sqrt(fx * fx + fy * fy)
  for _, b in ipairs(g.adj[s] or {}) do
    local dx, dy, l = dir(s, b)
    if fl < 1e-6 or (dx * fx + dy * fy) / fl > -0.2 then
      local k = s .. '>' .. b
      dist[k], edge[k] = l, { s, b }
      push(h, { l, k })
    end
  end
  local goal = nil
  while #h > 0 do
    local e = pop(h)
    local c, k = e[1], e[2]
    if c <= (dist[k] or math.huge) then
      local a, b = edge[k][1], edge[k][2]
      if b == t then goal = k; break end
      local ax, ay = dir(a, b)
      for _, n in ipairs(g.adj[b] or {}) do
        if n ~= a then
          local nx, ny, l = dir(b, n)
          if ax * nx + ay * ny >= cosMax then
            local k2 = b .. '>' .. n
            local c2 = c + l
            if c2 < (dist[k2] or math.huge) then
              dist[k2], prev[k2], edge[k2] = c2, k, { b, n }
              push(h, { c2, k2 })
            end
          end
        end
      end
    end
  end
  if not goal then return nil end
  local out = {}
  local k = goal
  while k do
    local a, b = edge[k][1], edge[k][2]
    table.insert(out, 1, { g.x[b], g.y[b] })
    if not prev[k] then table.insert(out, 1, { g.x[a], g.y[a] }) end
    k = prev[k]
  end
  return out
end

-- A far destination (the map's itinerary to a place whose tracks are not loaded yet): the way to the reachable node
-- of the loaded tracks nearest to (tx, ty) as the crow flies (Dijkstra over all the directed edges from the train,
-- the same turn rule), so the train heads that way; asked again as tiles come (nrailsmap). Returns the path and the
-- straight distance left from its end to (tx, ty).
function M.findToward(g, x, y, fx, fy, tx, ty)
  local s = M.nearest(g, x, y)
  if not s then return nil end
  local cosMax = math.cos(math.rad(M.TURN_DEG))
  local function dir(a, b)
    local dx, dy = g.x[b] - g.x[a], g.y[b] - g.y[a]
    local l = math.sqrt(dx * dx + dy * dy)
    if l < 1e-6 then return 0, 0, 0 end
    return dx / l, dy / l, l
  end
  local function left(n) return math.sqrt((g.x[n] - tx) ^ 2 + (g.y[n] - ty) ^ 2) end
  local h, dist, prev, edge = {}, {}, {}, {}
  local fl = math.sqrt(fx * fx + fy * fy)
  for _, b in ipairs(g.adj[s] or {}) do
    local dx, dy, l = dir(s, b)
    if fl < 1e-6 or (dx * fx + dy * fy) / fl > -0.2 then
      local k = s .. '>' .. b
      dist[k], edge[k] = l, { s, b }
      push(h, { l, k })
    end
  end
  local best, bestLeft = nil, left(s)
  while #h > 0 do
    local e = pop(h)
    local c, k = e[1], e[2]
    if c <= (dist[k] or math.huge) then
      local a, b = edge[k][1], edge[k][2]
      local lb = left(b)
      if lb < bestLeft - 1 then best, bestLeft = k, lb end
      local ax, ay = dir(a, b)
      for _, n in ipairs(g.adj[b] or {}) do
        if n ~= a then
          local nx, ny, l = dir(b, n)
          if ax * nx + ay * ny >= cosMax then
            local k2 = b .. '>' .. n
            local c2 = c + l
            if c2 < (dist[k2] or math.huge) then
              dist[k2], prev[k2], edge[k2] = c2, k, { b, n }
              push(h, { c2, k2 })
            end
          end
        end
      end
    end
  end
  if not best then return nil, bestLeft end
  local out = {}
  local k = best
  while k do
    local a, b = edge[k][1], edge[k][2]
    table.insert(out, 1, { g.x[b], g.y[b] })
    if not prev[k] then table.insert(out, 1, { g.x[a], g.y[a] }) end
    k = prev[k]
  end
  return out, bestLeft
end

local function distToPath(x, y, path)
  local best = math.huge
  for i = 1, #path - 1 do
    local ax, ay, bx, by = path[i][1], path[i][2], path[i + 1][1], path[i + 1][2]
    local dx, dy = bx - ax, by - ay
    local l2 = dx * dx + dy * dy
    local t = l2 > 0 and math.max(0, math.min(1, ((x - ax) * dx + (y - ay) * dy) / l2)) or 0
    local ex, ey = ax + t * dx - x, ay + t * dy - y
    local d = math.sqrt(ex * ex + ey * ey)
    if d < best then best = d end
  end
  return best
end
M._distToPath = distToPath

-- The turnouts the way runs through and the route it takes at each: { [id] = route index }. A route is the one whose
-- zone's end (where it is SPLIT_M from the others: one route only) the way passes.
function M.choices(switches, path)
  local out = {}
  if not path or #path < 2 then return out end
  for _, sw in ipairs(switches or {}) do
    if sw.at and distToPath(sw.at[1], sw.at[2], path) <= M.NODE_HIT_M then
      local best, bd = nil, M.ROUTE_HIT_M
      for i, r in ipairs(sw.routes or {}) do
        local line = r.line or r.arm
        if type(line) == 'table' and #line >= 2 then
          local d = distToPath(line[#line - 1], line[#line], path)
          if d <= bd then best, bd = i, d end
        end
      end
      if best then out[sw.id] = best end
    end
  end
  return out
end

-- The rows of every loaded tile's lines (roads.extTiles), the ghosts left out.
function M.rows(tiles)
  local out = {}
  for _, t in pairs(tiles or {}) do
    if t.railLines and not t.ghost then
      for _, row in ipairs(t.railLines) do out[#out + 1] = row end
    end
  end
  return out
end

-- The way's length (m).
function M.length(path)
  local L = 0
  for i = 1, #(path or {}) - 1 do
    L = L + math.sqrt((path[i + 1][1] - path[i][1]) ^ 2 + (path[i + 1][2] - path[i][2]) ^ 2)
  end
  return L
end

return M

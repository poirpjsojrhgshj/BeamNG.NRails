-- luajit mod/tests/test_scoping.lua  (every mod Lua file): no global read of a name the same file declares as a local.
-- A function that uses a local declared further down reads the (nil) global of that name instead: the BeamMP session's
-- test switch errored that way (remoteOwners) and roads.lua's prewarm after a level reload never ran (2026-10-22).
-- Reads LuaJIT's bytecode listing (luajit -bl): GGET is a global read.
local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local root = dir .. '/../beamng_earth/lua'

local files = {}
local p = io.popen('find "' .. root .. '" -name "*.lua"')
for f in p:lines() do files[#files + 1] = f end
p:close()
T.check(#files > 20, 'found the mod\'s Lua files: ' .. #files)

local bad = {}
for _, f in ipairs(files) do
  local src = io.open(f):read('*a')
  local listing = io.popen('luajit -bl "' .. f .. '" 2>/dev/null')
  local seen = {}
  for line in listing:lines() do
    local g = line:match('GGET.-"([%a_][%w_]*)"')
    if g and not seen[g] then
      seen[g] = true
      if src:find('\n%s*local%s+' .. g .. '%f[^%w_]') or src:find('\n%s*local%s+function%s+' .. g .. '%f[^%w_]')
          or src:find('\n%s*local%s+[%w_,%s]-,%s*' .. g .. '%f[^%w_]') then
        bad[#bad + 1] = f:match('lua/(.*)$') .. ': ' .. g
      end
    end
  end
  listing:close()
end
T.check(#bad == 0, 'no global reads of a file\'s own locals: ' .. table.concat(bad, ', '))
T.done('test_scoping')

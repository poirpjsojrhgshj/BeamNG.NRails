-- Minimal test helpers for running the mod's pure modules under plain luajit:
--   luajit mod/tests/test_geodesy.lua
-- Puts mod/beamng_earth/lua/ge/extensions on package.path, like the game does
-- (lua/ge/main.lua:58 extensions.addModulePath("lua/ge/extensions/")).

local dir = (arg and arg[0] or ''):match('^(.*)[/\\]') or '.'
package.path = dir .. '/../beamng_earth/lua/ge/extensions/?.lua;' .. package.path

local T = { failed = 0, passed = 0 }

function T.check(cond, msg)
  if cond then
    T.passed = T.passed + 1
  else
    T.failed = T.failed + 1
    print('FAIL: ' .. msg)
  end
end

function T.near(a, b, tol, msg)
  T.check(math.abs(a - b) <= tol, string.format('%s: got %.12g, want %.12g (tol %g)', msg, a, b, tol))
end

function T.done(name)
  print(string.format('%s: %d passed, %d failed', name, T.passed, T.failed))
  os.exit(T.failed == 0 and 0 or 1)
end

return T
